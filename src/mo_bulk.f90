MODULE mo_bulk
    ! This module either links to VECTRI or integrates
    ! the local source of disease, e.g., bacteria, ...
    !
    ! Miguel Garrido Zornoza 2024 
    ! mgarrizoraca@gmail.com
    !
    implicit none

    CONTAINS
        !
        !--------------------------------------------------------------------------------------
        !
        subroutine bulk_init(S,I,A,A_old,R,pop_dens,fS_0,fI_0,fA_0,fR_0,nxy,mask_pop,random,rand_seed)
        ! Initialize bulk model (SIR)
        ! For now all start as susceptible (can be changed to mimic the initial
        ! conditions of a real outbreak).
          implicit none

          integer, intent(in) :: nxy
          real, intent(in) :: fS_0,fI_0,fA_0,fR_0
          logical, allocatable, intent(in) :: mask_pop(:)    ! (nxy)
          real, allocatable, intent(in) :: pop_dens(:)
          real, allocatable, intent(inout) :: S(:),I(:),A(:),A_old(:),R(:)
          logical, intent(in)    :: random, rand_seed         ! Initialization method
          !
          ! Local use only
          integer :: ixy, roll
          real :: rand_f(3)
          real :: rand
          real :: cdf_health(4) ! Cumulative distribution to asign agent health based on initial profile
          !
          ! CDF for initial health status
          if (random) then
              ! To Do: We should here use disID input to build a disease-dependent dice
              cdf_health(:) = cumsum([0.25,0.25,0.25,0.25])/sum([0.25,0.25,0.25,0.25])
              !
          !else ! Follow initial condition profile
              
          end if
          !
          !if (random .and. (.not. rand_seed)) then
          !  print *, 'Random U[0,1)*pop SIAR(t=0) everywhere'
          !end if
          !
          do ixy = 1,nxy
            if (mask_pop(ixy)) then
               if (random .and. (.not. rand_seed)) then
                   !
                   !
                   call random_number(rand)
                   roll = find_face(rand,cdf_health(:),4)
                   call random_number(rand_f)
                   !
                   if (roll == 1) then
                       S(ixy) = rand_f(1)*pop_dens(ixy)                  ! rand_f(1) is fraction of total
                       I(ixy) = rand_f(2)*(1-rand_f(1))*pop_dens(ixy)    ! rand_f(2) is fraction of total-rand_f(1)
                       A(ixy) = rand_f(3)*(1-rand_f(1) &
                                            -rand_f(2)*(1-rand_f(1)))*pop_dens(ixy)    ! ...
                       R(ixy) = (1-rand_f(1) &
                                  -rand_f(2)*(1-rand_f(1)) &
                                  -rand_f(3)*(1-rand_f(1)-rand_f(2)*(1-rand_f(1))))*pop_dens(ixy)    ! ...
                    else if (roll == 2) then
                       I(ixy) = rand_f(1)*pop_dens(ixy)                  ! rand_f(1) is fraction of total
                       A(ixy) = rand_f(2)*(1-rand_f(1))*pop_dens(ixy)    ! rand_f(2) is fraction of total-rand_f(1)
                       R(ixy) = rand_f(3)*(1-rand_f(1) &
                                            -rand_f(2)*(1-rand_f(1)))*pop_dens(ixy)    ! ...
                       S(ixy) = (1-rand_f(1) &
                                  -rand_f(2)*(1-rand_f(1)) &
                                  -rand_f(3)*(1-rand_f(1)-rand_f(2)*(1-rand_f(1))))*pop_dens(ixy)    ! ...
                    else if (roll == 3) then
                       A(ixy) = rand_f(1)*pop_dens(ixy)                  ! rand_f(1) is fraction of total
                       R(ixy) = rand_f(2)*(1-rand_f(1))*pop_dens(ixy)    ! rand_f(2) is fraction of total-rand_f(1)
                       S(ixy) = rand_f(3)*(1-rand_f(1) &
                                            -rand_f(2)*(1-rand_f(1)))*pop_dens(ixy)    ! ...
                       I(ixy) = (1-rand_f(1) &
                                  -rand_f(2)*(1-rand_f(1)) &
                                  -rand_f(3)*(1-rand_f(1)-rand_f(2)*(1-rand_f(1))))*pop_dens(ixy)    ! ...
                    else
                       R(ixy) = rand_f(1)*pop_dens(ixy)                  ! rand_f(1) is fraction of total
                       S(ixy) = rand_f(2)*(1-rand_f(1))*pop_dens(ixy)    ! rand_f(2) is fraction of total-rand_f(1)
                       I(ixy) = rand_f(3)*(1-rand_f(1) &
                                            -rand_f(2)*(1-rand_f(1)))*pop_dens(ixy)    ! ...
                       A(ixy) = (1-rand_f(1) &
                                  -rand_f(2)*(1-rand_f(1)) &
                                  -rand_f(3)*(1-rand_f(1)-rand_f(2)*(1-rand_f(1))))*pop_dens(ixy)    ! ...
                    end if
                   !
                   !
               else
                   S(ixy) = fS_0*pop_dens(ixy)
                   I(ixy) = fI_0*pop_dens(ixy)
                   A(ixy) = fA_0*pop_dens(ixy)
                   R(ixy) = fR_0*pop_dens(ixy)
               end if
            end if
          end do
          
          A_old = A

        end subroutine bulk_init
        !
        !--------------------------------------------------------------------------------------
        !
        pure subroutine bulk_integrate_SIAR_cholera(ixy,S,I,A,R,pop_dens,F,dt,mu,rho,sigma,gamma,alpha,eps)
            !Integrate SIAR model 
            implicit none

            integer, intent(in) :: ixy                              ! Grid point under scope
            real, intent(in) :: eps                                 ! Numerical tolerance
            real, intent(in) :: dt                                  ! Time step
            real, intent(in) :: mu, rho, sigma, gamma, alpha        ! Disease parameters
            real, allocatable, intent(in) :: F(:)                   ! Force of infection (len=nxy)
            real, allocatable, intent(in) :: pop_dens(:)            ! Human population density (len=nxy)
            real, allocatable, intent(inout) :: S(:),I(:),A(:),R(:) ! SIAR arrays (len=nxy)

            ! Explicit Euler for now ; dt = 1
            S(ixy) = S(ixy) + (mu*(pop_dens(ixy)-S(ixy)) - F(ixy)*S(ixy) + rho*R(ixy))*dt
            I(ixy) = I(ixy) + (sigma*F(ixy)*S(ixy) -(mu+gamma+alpha)*I(ixy))*dt
            A(ixy) = A(ixy) + ((1-sigma)*F(ixy)*S(ixy) - (mu+gamma)*A(ixy))*dt
            R(ixy) = R(ixy) + (gamma*(I(ixy)+A(ixy)) - (rho+mu)*R(ixy))*dt

            ! Apply numerical threshold
            if (S(ixy) .lt. eps) then 
                S(ixy)=0.
            end if
            if (I(ixy) .lt. eps) then 
                I(ixy)=0.
            end if
            if (A(ixy) .lt. eps) then 
                A(ixy)=0.
            end if
            if (R(ixy) .lt. eps) then 
                R(ixy)=0.
            end if
                
        end subroutine bulk_integrate_SIAR_cholera
        !--------------------------------------------------------------------------------------
        !






        !============ Functions ===============
        !
        function cumsum(a) result(r)
            ! https://fortran-lang.discourse.group/t/what-is-the-fastest-way-to-do-cumulative-sum-in-fortran-to-mimic-matlab-cumsum/1976/11
            !
            real, intent(in) :: a(:)
            real :: r(size(a))
            integer :: i
            !
            r(:) = [(sum(a(1:i)),i=1,size(a))]
            !
        end function cumsum
        !
        function find_face(r,cum_distr,sides) result(roll)
            ! r: uniformly distributed random number, [0,1)
            ! cum_distr: cumulative distribution (not normalized) of probablities (the weights of each face of the dice)
            ! sides: number of dice sides
            implicit none
            !
            real, intent(in) :: r, cum_distr(sides)
            integer, intent(in) :: sides
            integer   :: roll
            !
            ! Local use only
            integer :: j
            !
            do j = 1, sides
                if (r <= cum_distr(j)) then
                    !
                    roll = j
                    !
                    exit
                end if 
            end do
            !
        end function find_face
end MODULE mo_bulk