MODULE mo_source
    ! This module either links to VECTRI or integrates
    ! the local source of disease, e.g., bacteria, ...
    !
    ! Author: Miguel Garrido Zornoza (2024) 
    ! Contact: mgarrizoraca@gmail.com
    !
    implicit none

    CONTAINS
        !
        !--------------------------------------------------------------------------------------
        subroutine source_init(Q,B_0,beta,m,nxy,agents,seed,random,rand_seed,exc,out_rain,exc_clim,B,B_old,F,radial,pop_dens,mask_pop,xy_seed)
        ! Initialize source of disease
        ! For a random place - in the future could be one chosen from empirical data
          implicit none
          !
          !
          real, intent(in) :: B_0, beta, m
          integer, intent(in) :: nxy
          logical, intent(in) :: agents
          logical, intent(in) :: radial
          real, allocatable, intent(in)  :: Q(:,:) ! Probability of visit matrix
          integer, intent(in) :: seed              !
          integer, intent(inout) :: xy_seed
          logical, intent(in)    :: random, rand_seed        ! Initialization method
          logical, intent(in)    :: out_rain                 ! Rainfall flag
          real, allocatable, intent(in)    :: pop_dens(:)    ! (nxy)
          logical, allocatable, intent(in) :: mask_pop(:)    ! (nxy)
          real, allocatable, intent(out) :: exc(:)       ! 1D long array for the excretion events
          real, allocatable, intent(out) :: exc_clim(:)  ! 1D long array for climate-driven excretion events
          real, allocatable, intent(out) :: B(:)         ! Array of bacterial density (len=nxy)
          real, allocatable, intent(out) :: B_old(:)     ! Array of bacterial density (len=nxy)
          real, allocatable, intent(out) :: F(:)         ! Force of infection (len=nxy)
          !
          ! Local use only
          integer :: ixy
          logical :: land=.false.
          real :: rand_B(nxy)
          !
          if (rand_seed) then
             ! if ((.not. radial)) then         - old code [potential deletion]
             !   xy_seed = ceiling(nxy/2.)      - 
             ! else                             - 
            call srand(seed)
            do while (.not. land)
              xy_seed = ceiling(rand()*real(nxy))
              if (mask_pop(xy_seed)) then
                land=.true.
                print *, 'Initializing source of infection --> Found land!'
                print '("Population at source : ",f8.2," [km^-2]")', pop_dens(xy_seed)
        
              end if
            end do
             ! end if                           - old code [potential deletion]
          end if ! random
          !
          allocate(B(nxy))
          allocate(B_old(nxy))
          !
          !
          B(:) = 0.
          if (random) then ! initialize using random place
              if (rand_seed) then
                  B(xy_seed) = B_0
              else 
                  print *, 'Random U[0,1) B(t=0) everywhere'
                  call random_number(rand_B)
                  B(:) = rand_B
                  where(.not. mask_pop) B(:) = 0.
              end if
          else ! everywhere
            where(mask_pop) B(:) = B_0
          end if
          B_old(:)=B(:)
          !
          ! Allocate and initialize excretion arrays
          if (agents) then
              allocate(exc(nxy))
              exc(:) = 0.
              !
              if (out_rain) then
                allocate(exc_clim(nxy))
                exc_clim(:) = 0.
              end if
          end if
          !
          !
          if (.not. agents) then
              allocate(F(nxy))
              do ixy = 1,nxy
                F(ixy)  = beta*((1-m)*B(ixy)/(1.+B(ixy)) + m*sum(B(:)/(1.+B(:))*Q(ixy,:)))
              end do
          end if
          !
        end subroutine source_init
        !--------------------------------------------------------------------------------------
        !
        ! Integrate bacterial load with explicit asymptomatics
        pure subroutine source_integrate_B(ixy,itime,nxy,agents,exc,out_rain,exc_clim,rainfall,I,D,Q,mask_grav,B_old,A_old,dt,mu_b,theta_e,theta_p,beta,m,eps,B,F)
            ! Update bacterial concentration (B) and force of infection (F)
            implicit none

            integer, intent(in) :: ixy                     ! Grid point 
            integer, intent(in) :: itime                   ! Time step
            integer, intent(in) :: nxy                     ! Number of lattice points 
            logical, intent(in) :: agents                  ! Agent flag
            real, intent(in) :: dt                         ! Time step (=1day)
            real, intent(in) :: mu_b, beta                 ! Disease parameters 
            real, intent(in) :: theta_e, theta_p
            real, intent(in) :: m                          ! Mobility parameters
            real, intent(in) :: eps                        ! Numerical tolerance
            logical, intent(in)              :: out_rain   ! Rainfall flag
            real, intent(in)                 :: rainfall(:,:)! 2D long array for rainfall (nxy,t=itime); accepts allocatable or pointer actual arg
            real, allocatable, intent(in)    :: I(:)       ! Density of infected symptomatic people (len=nxy)
            real, allocatable, intent(in)    :: A_old(:)   ! Old density of infected asymptomatic people (len=nxy)
            real, allocatable, intent(in)    :: D(:)       ! Dilution factor (len=nxy)
            real, allocatable, intent(in)    :: Q(:,:)     ! Probability of visit matrix
            real, allocatable, intent(in)    :: exc(:)       ! 1D long array for excretion events
            real, allocatable, intent(in)    :: exc_clim(:)  ! 1D long array for clim-driven excretion events
            logical, allocatable, intent(in) :: mask_grav(:,:)! (nxy,nxy)
            real, allocatable, intent(inout) :: B(:), F(:) ! Bacterial density and force of infection (len=nxy)
            real, allocatable, intent(inout) :: B_old(:)   ! Old bacterial density

            
            ! Local use only
            real :: mob_F       ! Force of infection from mobile population
            real :: exc_B       ! Excretion term from asymptomatics
            integer :: ixy_2    ! Looping index
            real :: Mob

            ! This loop slows down the whole PROGRAM --> introduced a cut-off distance
            ! for the potential (mask_grav)

            ! If no agents we need to calculate mobility contributions to excretion and force of infection
            if (.not. agents) then
                exc_B = 0.
                mob_F = 0.
                !do concurrent (ixy_2=1:nxy, mask_grav(ixy_2,ixy)) 
                do ixy_2=1,nxy  
                    if (mask_grav(ixy_2,ixy)) then ! Remember mask_grav info has swapped indexes for efficiency
                         exc_B = exc_B +  A_old(ixy_2)*Q(ixy_2,ixy)
                         mob_F = mob_F + (B_old(ixy_2)/(1.+B_old(ixy_2)))*Q(ixy,ixy_2) 
                    end if
                end do
            end if

            ! ========== Take time step =======================
            ! Explicit Euler for now ; dt = 1 day
            ! Update bacterial concentration
            ! If bulk density
            if ((D(ixy) > 0.) .and. (.not. agents)) then
                Mob = I(ixy) + (1-m)*A_old(ixy)+ m*exc_B ! For clarity we save the common term
                B(ixy) = B_old(ixy) + (-mu_b*B_old(ixy) + Mob*D(ixy)*(theta_e+theta_p*rainfall(ixy,itime)))*dt


            !
            ! If agents = .true. the mobility terms have already been calculated in agents_update
            else if ((D(ixy) > 0.) .and. agents) then
                B(ixy) = B_old(ixy) + (-mu_b*B_old(ixy)+exc(ixy))*dt

                if (out_rain) then
                    B(ixy) = B(ixy) + exc_clim(ixy)*dt
                end if

            ! If mask_pop = .false. (equivalently D = 0.)
            else 
                B(ixy) = B_old(ixy) + (-mu_b*B_old(ixy))*dt
            end if 
            !
            ! Apply numerical threshold
            if (B(ixy) .lt. eps) then 
                B(ixy)=0.
            end if
            !
            if (.not. agents) then
                ! Update force of infection
                F(ixy) = beta*((1-m)*B_old(ixy)/(1.+B_old(ixy)) + m*mob_F)
                if (F(ixy) .lt. eps) then 
                    F(ixy)=0.
                end if
            end if
            !   
        end subroutine source_integrate_B
end MODULE mo_source