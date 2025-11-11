MODULE mo_grid
  ! This module ...
  !
  ! Author: Miguel Garrido Zornoza (2024) 
  ! Contact: mgarrizoraca@gmail.com
  !
  USE mo_const
  USE mo_control
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
      integer :: indx, k

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

      case (1) ! Malaria (SEIR)

        allocate(S(nxy))
        allocate(E(nxy))
        allocate(I(nxy))
        allocate(A(nxy))
        allocate(R(nxy))
        !
        allocate(EIR(nxy))
        allocate(imm(nxy))
        allocate(hbr(nxy))

        EIR(:) = 0.
        imm(:) = 0.
        hbr(:) = 0.

        if (diag_age) then
          !
          allocate(Sa(nxy,size(age_blocks(:))))
          allocate(Ea(nxy,size(age_blocks(:))))
          allocate(Ia(nxy,size(age_blocks(:))))
          allocate(Aa(nxy,size(age_blocks(:))))
          allocate(Ra(nxy,size(age_blocks(:))))
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
                                  x_coord_1d,y_coord_1d,radial,nlon,nlat,lat_coord,lon_coord, L) !*********
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





