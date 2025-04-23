MODULE mo_mobility
  ! This module ...
  !
  ! Miguel Garrido Zornoza 2024 
  ! mgarrizoraca@gmail.com
  !
  implicit none
  
  CONTAINS 
    !
    !--------------------------------------------------------------------------------------
    !
    subroutine mob_dist_init(nxy,x_coord_1d,y_coord_1d,lon_coord,lat_coord,dx,dy,input,Re,pi,mask_pop,dist) !***************************
      ! Calculate distances between all pairs for a given grid
      ! Currently calculates the shortest distance - could  be updated
      ! to calculate shortest distance for a given network 
      implicit none

      logical, intent(in)              :: input         ! Input flag
      integer, intent(in)              :: nxy           ! Total number of lattice points (= nlon*nlat)
      integer, allocatable, intent(in) :: x_coord_1d(:) !
      integer, allocatable, intent(in) :: y_coord_1d(:) !
      real, allocatable, intent(in)    :: lon_coord(:)  !
      real, allocatable, intent(in)    :: lat_coord(:)  !
      real, intent(in)                 :: Re            ! Average radius of the Earth
      real, intent(in)                 :: pi            ! 3.14...
      real, intent(in)                 :: dx, dy        ! 
      logical, allocatable, intent(in) :: mask_pop(:)   ! (nxy)
      real, allocatable, intent(out)   :: dist(:,:)     ! Distance matrix
      
      ! Local use only
      integer :: ixy_1,ixy_2
      real :: dlat, dlon

      allocate(dist(nxy,nxy))
      
      do ixy_1=1,nxy
        write(*,'(1a1,A21,F6.1,A2)', advance='no') char(13),'Calculating distances',(real(ixy_1)/real(nxy)*100.),' %'
        if ((mask_pop(ixy_1))) then
          do ixy_2=ixy_1+1,nxy
            if ((mask_pop(ixy_2))) then
              if ((input)) then 
                ! - Assume geographic coordinates and
                !   calculate geodesic distance between two points. 
                ! - Spherical Earth approximation that
                !   takes into account change in meridian distance with latitude
                dlat = Re*(2*sin(0.5*(lat_coord(y_coord_1d(ixy_1))-lat_coord(y_coord_1d(ixy_2)))*pi/180.))* &
                          cos(0.5*(lon_coord(x_coord_1d(ixy_1))-lon_coord(x_coord_1d(ixy_2)))*pi/180.)
    
                dlon = Re*(2*cos(0.5*(lat_coord(y_coord_1d(ixy_1))+lat_coord(y_coord_1d(ixy_2)))*pi/180.))* &
                          sin(0.5*(lon_coord(x_coord_1d(ixy_1))-lon_coord(x_coord_1d(ixy_2)))*pi/180.)
                 
              else ! Flat grid for conceptual case
                dlat = (y_coord_1d(ixy_1)-y_coord_1d(ixy_2))*dy
                dlon = (x_coord_1d(ixy_1)-x_coord_1d(ixy_2))*dx
              end if
              ! Save distance and its symmetric element
              dist(ixy_1,ixy_2) = sqrt((dlat)**2+(dlon)**2)
              dist(ixy_2,ixy_1) = dist(ixy_1,ixy_2) 
            end if
          end do
        end if
      end do
      write(*,*) ' '
    !  print '("Distance between grid points is aprox. -- dx = ",f6.2," dy = ",f6.2," [km]")', dist(1,2),dist(1,size(lon_coord)+1)
    end subroutine mob_dist_init
    !
    !--------------------------------------------------------------------------------------
    !
    subroutine mob_gravity_init(nxy,agents,eps,mask_pop,mask_grav,mask_mob,D_grav,pop_dens,dist,Q,Q_cum) !******************************************
      ! Calculate 
      !     1) Visit probabilities of gravity model from
      !        Lorenzo et al. (http://doi.org/10.1098/rsif.2014.0840)
      !        Needs: distance between all pairs and human population density
      !     2) Gravity mask: for a given cut-off distance calculate a boolean 
      !        matrix of shape (nxy,nxy) with connected points.
      implicit none

      integer, intent(in)              :: nxy           ! Total number of lattice points (= nlon*nlat)
      real, intent(in)                 :: D_grav,eps    !
      real, allocatable, intent(in)    :: pop_dens(:)   ! Population density [km^2]
      real, allocatable, intent(in)    :: dist(:,:)     ! Distance matrix
      logical, allocatable, intent(in) :: mask_pop(:)   ! (nxy)
      logical, intent(in)              :: agents        !
      logical, allocatable, intent(out):: mask_mob(:)   ! (nxy)
      logical, allocatable, intent(out):: mask_grav(:,:)! (nxy,nxy)
      real, allocatable, intent(out)   :: Q(:,:)        ! Probability of visit matrix
      real, allocatable, intent(out)   :: Q_cum(:,:)    !

      ! Local use only
      real    :: norm ! Normalization factor for gravity model
      real    :: norm_dice  ! Normalization factor for agent dice
      integer :: ixy_1,ixy_2,counter

      print *, 'Allocating weights ...'
      allocate(Q(nxy,nxy))
      allocate(mask_grav(nxy,nxy))

      Q(:,:) = 0.
      mask_grav(:,:) = .false.

      ! Mobility dice for agents
      if (agents) then
        allocate(Q_cum(nxy,nxy))
        allocate(mask_mob(nxy))
        Q_cum(:,:) = 0.
        mask_mob(:) = .true.
      end if
      
      counter = 0

      outer_loop: do ixy_1=1,nxy
        norm = 0.
        norm_dice = 0.
        write(*,'(1a1,A19,F6.1,A2)', advance='no') char(13),'Calculating weights',(real(ixy_1)/real(nxy)*100.),' %'
        if (mask_pop(ixy_1)) then
          counter = counter + 1
          do concurrent (ixy_2=1:nxy, mask_pop(ixy_2))
          !do ixy_2=1,nxy         ! Equivalent explicit mask
            !if (mask_pop(ixy_2)) then
              !
              norm = norm + pop_dens(ixy_2)*exp(-dist(ixy_2,ixy_1)/D_grav)   ! Column-major (dist(:,:) indexes switched ; symmetric mat)
              !
            !end if
          end do 
          
          ! Remove local grid point
          norm = norm - pop_dens(ixy_1)

          ! Safety check
          if (norm < eps) then
              Q(ixy_1,:) = 0.
          else
              ! Calculate weights
              inner_loop: do ixy_2=1,nxy
                  if (mask_pop(ixy_2)) then
                    !
                    Q(ixy_1,ixy_2) = pop_dens(ixy_2)*exp(-dist(ixy_2,ixy_1)/D_grav)/norm
                    !
                    ! Create gravity cut-off at 1 times the e-folding distance
                    if (dist(ixy_2,ixy_1)<1.*D_grav*(log(pop_dens(ixy_2))+1) .and. (ixy_2 /= ixy_1)) then
                      mask_grav(ixy_2,ixy_1) = .true. ! Store it "backwards" since we can then loop over the
                    end if                            ! first index (rows) and go faster (FORTRAN is column-major)
                  end if

                  if (agents) then
                    !
                    
                    ! To use it as a dice efficiently we switch the indexes in the cummulative array
                    ! and apply the cut-off mask asigning zero probability to points outside
                    !
                    if (mask_grav(ixy_2,ixy_1) .and. mask_pop(ixy_2)) then
                      !
                      norm_dice = norm_dice + Q(ixy_1,ixy_2)   ! Include in normalization factor
                      Q_cum(ixy_2,ixy_1) = norm_dice     ! By building the dice in this way we have a 
                                                   ! cummulative array only in the indexes where this condition is true
                                                   ! The rest of the indexes have zero value and when the dice is thrown
                                                   ! they are automatically excluded.
                      !
                    else 
                      Q_cum(ixy_2,ixy_1) = 0.      ! Redundant since its zero already (written for clarity)
                    end if
                    !
                  end if
              end do inner_loop
              !
          end if
          ! Set diagonal back to zero
          Q(ixy_1,ixy_1)= 0.
          !
          ! Normalize cummulative array
          if (agents .and. (norm_dice > eps)) then ! Second condition is for cases where there are agents but cannot move anywhere
            !
            Q_cum(:,ixy_1) = Q_cum(:,ixy_1)/norm_dice
            !print *, norm_dice,sum(Q_cum(:,ixy_1))

          else if (agents .and. (norm_dice < eps)) then!
            mask_mob(ixy_1) = .false. ! If norm_dice is zero it means agents are at ixy_1
                                      ! but the "grav" and "pop" masks don't allow them to move
                                      ! we save this info and use it in the agents_update subroutine
            !
          end if

          
          
        end if ! mask_pop(ixy_1)
      end do outer_loop
      
      ! Numerical tolerance
      where(Q < eps) Q  = 0.
      write(*,*) ' '
      print *, "Number of populated land points: ", counter

    end subroutine mob_gravity_init
    !
    !--------------------------------------------------------------------------------------
    !
    subroutine mob_radiation_init !************************************************************
      ! Radiation model

    end subroutine mob_radiation_init
    !
    !--------------------------------------------------------------------------------------
    !
  !=
  !============ Functions ===============
  
end MODULE mo_mobility
