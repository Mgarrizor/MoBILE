MODULE mo_grid
  ! This module ...
  !
  ! Author: Miguel Garrido Zornoza (2024) 
  ! Contact: mgarrizoraca@gmail.com
  !
  USE mo_const
  USE mo_control
  USE omp_lib
  !
  !
  implicit none
  
  CONTAINS

  !===================== Subroutines =================================

  subroutine grid_dis(idis,nxy,S,E,I,A,A_old,R,EIR,imm,hbr)
      implicit none

      integer, intent(in) :: idis
      integer, intent(in) :: nxy
      real, allocatable, target, intent(out) :: S(:),E(:),I(:),A(:),R(:)
      real, allocatable, intent(out) :: A_old(:),EIR(:),imm(:), hbr(:)

      ! Local use only
      integer :: indx, k, nthreads

      nthreads = omp_get_max_threads()

      SELECT case(idis)
      case (0) ! Cholera (SIAR)

        allocate(S(nxy))
        allocate(I(nxy))
        allocate(A(nxy))
        allocate(A_old(nxy))
        allocate(R(nxy))

        ! Look up table for pointer approach to gather bulk diagnostics
        status_pointer(1)%arr_p => S
        status_pointer(2)%arr_p => I
        status_pointer(3)%arr_p => A
        status_pointer(4)%arr_p => R
        allocate(status_pointer(1)%arr_p_priv(nxy,nthreads))
        allocate(status_pointer(2)%arr_p_priv(nxy,nthreads))
        allocate(status_pointer(3)%arr_p_priv(nxy,nthreads))
        allocate(status_pointer(4)%arr_p_priv(nxy,nthreads))

      case (1) ! Malaria (SEIR)

        allocate(S(nxy))
        allocate(E(nxy))
        allocate(I(nxy))
        allocate(I_new(nxy))
        allocate(A(nxy))
        allocate(R(nxy))
        !
        allocate(EIR(nxy))
        allocate(P1(nxy))
        allocate(imm(nxy))
        allocate(hbr(nxy))
        allocate(EIR_priv(nxy,nthreads))
        allocate(P1_priv(nxy,nthreads))
        allocate(esc_log(nxy))
        esc_log(:) = 0._8
        allocate(imm_priv(nxy,nthreads))
        allocate(hbr_priv(nxy,nthreads))

        EIR(:) = 0.
        P1(:) = 0.
        imm(:) = 0.
        hbr(:) = 0.

        if (diag_age) then
          !
          call init_age_labels()
          !
          allocate(Sa(nxy,size(age_blocks(:))))
          allocate(Ea(nxy,size(age_blocks(:))))
          allocate(Ia(nxy,size(age_blocks(:))))
          allocate(Ia_new(nxy,size(age_blocks(:))))
          allocate(Aa(nxy,size(age_blocks(:))))
          allocate(Ra(nxy,size(age_blocks(:))))
          !
          allocate(imm_a(nxy,size(age_blocks(:))))
          !
          allocate(N_a(nxy,size(age_blocks(:))))
          !
          ! Per-block staging (see array_pointers in mo_const.f90): one column
          ! set per BLOCK, shared by every exact age that maps to it below.
          ! Sa/Ea/Ra are never output or read anywhere -- no staging for them.
          allocate(Ia_priv(nxy,nthreads,size(age_blocks(:))))
          allocate(Aa_priv(nxy,nthreads,size(age_blocks(:))))
          allocate(imm_a_priv(nxy,nthreads,size(age_blocks(:))))
          allocate(N_a_priv(nxy,nthreads,size(age_blocks(:))))
          allocate(Ia_new_priv(nxy,nthreads,size(age_blocks(:))))
          !
          ! Look up table for age blocks
          do indx = 0, size(Iage_stat_ptr(1,:))-1 ! Loop over ages, starting at 0
            !
            k = find_block(indx,age_blocks(:),size(age_blocks(:)))
            !
            Iage_stat_ptr(1,indx+1)%arr_p => Sa(:,k)
            Iage_stat_ptr(2,indx+1)%arr_p => Ea(:,k)
            Iage_stat_ptr(3,indx+1)%arr_p => Ia(:,k)
            Iage_stat_ptr(4,indx+1)%arr_p => Aa(:,k)
            Iage_stat_ptr(5,indx+1)%arr_p => Ra(:,k)
            !
            Iage_stat_ptr(6,indx+1)%arr_p => imm_a(:,k)
            !
            Iage_stat_ptr(7,indx+1)%arr_p => N_a(:,k)
            !
            Iage_stat_ptr(8,indx+1)%arr_p => Ia_new(:,k)
            !
            Iage_stat_ptr(3,indx+1)%arr_p_priv => Ia_priv(:,:,k)
            Iage_stat_ptr(4,indx+1)%arr_p_priv => Aa_priv(:,:,k)
            Iage_stat_ptr(6,indx+1)%arr_p_priv => imm_a_priv(:,:,k)
            Iage_stat_ptr(7,indx+1)%arr_p_priv => N_a_priv(:,:,k)
            Iage_stat_ptr(8,indx+1)%arr_p_priv => Ia_new_priv(:,:,k)
          end do
        else 
          !allocate(I(nxy))
        end if

        ! Look up table for pointer approach to gather bulk diagnostics
        status_pointer(1)%arr_p => S
        status_pointer(2)%arr_p => E
        status_pointer(3)%arr_p => I
        status_pointer(4)%arr_p => A
        status_pointer(5)%arr_p => R

        status_pointer(6)%arr_p => I_new

        allocate(status_pointer(1)%arr_p_priv(nxy,nthreads))
        allocate(status_pointer(2)%arr_p_priv(nxy,nthreads))
        allocate(status_pointer(3)%arr_p_priv(nxy,nthreads))
        allocate(status_pointer(4)%arr_p_priv(nxy,nthreads))
        allocate(status_pointer(5)%arr_p_priv(nxy,nthreads))
        allocate(status_pointer(6)%arr_p_priv(nxy,nthreads))


      case (2) ! Dengue [Non-functional]

      case default
        print *, "Incorrect case, choose disID between: 0 (cholera) and 1 (malaria)"
        STOP
      end SELECT
      
  end subroutine grid_dis
  !
  function find_block(iage,arr_blocks,nblocks) result(b)
            ! iage: age [years]
            ! arr_blocks: array with age intervals delimiting blocks
            ! nblocks: number of blocks
            implicit none
            !
            integer, intent(in) :: arr_blocks(nblocks)
            integer, intent(in) :: iage,nblocks
            integer   :: b
            !
            ! Local use only
            integer :: j
            b = 0 
            !
            do j = 1, nblocks-1
                if (iage < arr_blocks(1)) then  ! New-borns
                    !
                    b = 1
                    !
                    EXIT
                else if (iage >= arr_blocks(nblocks)) then  ! Older than upper limit
                    !
                    b = nblocks
                    !
                    EXIT
                else if ((iage < arr_blocks(j+1)) .and. (iage >= arr_blocks(j))) then
                    !
                    b = j+1
                    !
                    EXIT
                end if 
            end do
            !
        end function find_block
  !--------------------------------------------------------------------------------------
  subroutine interv_field_init(nxy,x_coord_1d,y_coord_1d,lon_coord,lat_coord)
  !===
      ! f(x) = interv_factor * exp(interv_beta * u(x)),  u measured in degrees from
      ! the domain centre along the axis at bearing interv_theta (clockwise from
      ! north), then capped at 1 (f > 1 would mean enhanced transmission).
      ! Centring u makes interv_factor the geometric mean of the field, so it keeps
      ! its meaning as the uniform-equivalent level.
      implicit none
      integer, intent(in) :: nxy
      integer, allocatable, intent(in) :: x_coord_1d(:), y_coord_1d(:)
      real,    allocatable, intent(in) :: lon_coord(:), lat_coord(:)
      real :: lat0, lon0, u, ct, st, dtor
      integer :: j

      allocate(interv_f(nxy))
      dtor = acos(-1.)/180.
      ct = cos(interv_theta*dtor); st = sin(interv_theta*dtor)
      lat0 = 0.5*(minval(lat_coord) + maxval(lat_coord))
      lon0 = 0.5*(minval(lon_coord) + maxval(lon_coord))
      do j = 1, nxy
          u = (lat_coord(y_coord_1d(j)) - lat0)*ct + (lon_coord(x_coord_1d(j)) - lon0)*st
          interv_f(j) = min(interv_factor*exp(interv_beta*u), 1.0)
      end do
      if (interv_beta /= 0.) then
          print '(" Intervention field: f0=",f7.4," beta=",f7.4,"/deg theta=",f6.1," deg")', &
              interv_factor, interv_beta, interv_theta
          print '("   f range ",f7.4," - ",f7.4,"   capped cells: ",i0)', &
              minval(interv_f), maxval(interv_f), count(interv_f >= 1.0)
      end if
  end subroutine interv_field_init

  !--------------------------------------------------------------------------------------

  subroutine grid_allocate(nxy,nlon,nlat,y_coord_1d,x_coord_1d)
      implicit none

      integer,           intent(out) :: nxy, nlon, nlat
      integer, allocatable, intent(out) :: x_coord_1d(:)
      integer, allocatable, intent(out) :: y_coord_1d(:)

      ! Local use only
      integer :: ix  ! Looping short index
      integer :: iy  ! Looping short index
      integer :: i_1d! Dummy index to map 2D to 1D

      ! Map 2D grid into a 1D long array
      ! 
      allocate(y_coord_1d(nxy))
      allocate(x_coord_1d(nxy))
      do ix=1,nlon
        do iy=1,nlat
          i_1d = ix + nlon*(iy-1)
          y_coord_1d(i_1d) = iy
          x_coord_1d(i_1d) = ix
        end do
      end do
      !
  end subroutine grid_allocate
  
  !--------------------------------------------------------------------------------------

  subroutine grid_no_input(nxy,dx,dy,ncity,seed,H_0,D_pop,pop_dens,D, &
                                  x_coord_1d,y_coord_1d,radial,nlon,nlat,lat_coord,lon_coord, L) 
  
          ! Hardcoded grid configuration for conceptual case.
          ! Index -------------------------------
          ! 0) Map 2D grid into a 1D long array
          ! 1) Initialize Diagnostics
          ! 2) Build radial city
          !--------------------------------------
      implicit none
      ! From main Program
      integer, intent(inout) :: nxy      ! Total number of lattice points (= nlon*nlat)
      real, intent(inout)    :: dx       ! Horizontal discretization 
      real, intent(inout)    :: dy       ! Vertical     "     "
      integer, intent(in) :: ncity    ! Number of radial cities in the grid
      integer, intent(in) :: seed     !
      
      real, intent(in)    :: H_0      ! Human population density at city centre
      real, intent(in)    :: D_pop    ! e-folding for distance factor in gravity model
      logical, intent(in) :: radial   ! if .true. build radial city, otherwise uniform

      integer, allocatable, intent(in) :: x_coord_1d(:) ! 
      integer, allocatable, intent(in) :: y_coord_1d(:) !

      real, allocatable, intent(out) :: pop_dens(:)   ! Population density [km^2]
      real, allocatable, intent(out) :: D(:)          ! Dilution factor

      ! To be moved somewhere else
      integer, intent(inout) :: nlon, nlat
      real, allocatable, intent(out) :: lat_coord(:)
      real, allocatable, intent(out) :: lon_coord(:)
      real :: L
      integer :: i
      
      ! Local use only
      integer :: ixy ! Looping long index
      real    :: r   ! Distance
      integer :: j   ! Dummy index
      integer :: xycent ! City centre

      print *, 'Mode: conceptual (no input files)'

      !
      dx=L/real(nlon) ! Horizontal discretization
      dy=L/real(nlat) ! Vertical discretization
      !
      allocate(lon_coord(nlon))
      allocate(lat_coord(nlat))
      lon_coord = (/(dx*i, i = 1, nlon)/)
      lat_coord = (/(dy*i, i = 1, nlat)/)
      !
      ! 2) Choose between uniform and radial city
      
      allocate(pop_dens(nxy))
      allocate(D(nxy))

      if ((.not. radial)) then
        pop_dens(:) = H_0
      elseif ((radial)) then

        if ((ncity==1)) then ! If we have only one city we place it in the centre
          if (MOD(nxy,2) .eq. 0) then ! If N is even 
            print *, 'Choose N odd --> Stop'
            stop
          else                      ! Else N is odd and city centre is one point
            xycent = ceiling(nxy/2.)
  
          end if
  
          do ixy=1,nxy 
            
              r = SQRT(((y_coord_1d(ixy)-y_coord_1d(xycent))*dy)**2+((x_coord_1d(ixy)-x_coord_1d(xycent))*dx)**2)
              pop_dens(ixy) = H_0*EXP(-r/D_pop)
  
          end do
  
        else ! We have more than one city
          call srand(seed)
          do j=1,ncity
            xycent = ceiling(rand(seed)*real(nxy))
            do ixy=1,nxy 
           
             r = SQRT(((y_coord_1d(ixy)-y_coord_1d(xycent))*dy)**2+((x_coord_1d(ixy)-x_coord_1d(xycent))*dx)**2)
             pop_dens(ixy) = pop_dens(ixy) + H_0*EXP(-r/D_pop)
  
            end do  
          end do
        endif
      end if

      where(pop_dens < 0.01) pop_dens  = 0.
      where(pop_dens < 0.01) D = 0.
      where(pop_dens > 0.01) D = 1/log(pop_dens+1)


      ! Not very effective (neglecting polar symmetry)
      ! For production code, it is recommended to use
      ! the intrisinc function norm2 (https://gcc.gnu.org/onlinedocs/gfortran/NORM2.html)
      
  end subroutine grid_no_input
  


  !===================== Functions ===================================

end MODULE mo_grid





