MODULE mo_vectri
!
! Miguel Garrido Zornoza (mgarrizoraca@gmail.com) 2025
!
use mo_constants  !--VECTRI--
use mo_methods    !--VECTRI--

use mo_const      !--AB--

implicit none
!----------------------------------------------------------------------------------------------
! Check list:
!                           !--------------- mo_vectri.f90 (AB) --------------!
! Variable                  Defined (AB) Allocated (AB)   Initialized (AB)    !    Defined (VECTRI)    Allocated (VECTRI)   Initialized (VECTRI)
                                                                              !
! == BASIC ====                                                               !
                                                                              !
! rmasslarv(0:nlarv)            Y                Y            Y                       mo_vectri.f90      mo_interface.f90      mo_interface.f90
! rlarv(0:nlarv,nlon,nlat)      Y                Y            Y                       mo_vectri.f90      mo_interface.f90      mo_interface.f90
! rvect(0:ninfv,nlon,nlat)      Y                Y            Y                       mo_vectri.f90      mo_interface.f90      mo_interface.f90 
! rzoophilic(nlon,nlat)         Y                Y            Y                       mo_vectri.f90      mo_interface.f90      mo_interface.f90
! rbitezoo(nlon,nlat)           Y                Y            Y                       mo_vectri.f90      mo_interface.f90      mo_interface.f90
! zsurvp_larv(0:nlarv)          Y                Y            Y(=1.)                  mo_vectri.f90      mo_vectri.f90                N

! zvect_density(nlon,nlat)                                                            mo_vectri.f90      mo_vectri.f90
! zvect_one_d_density(nlon,nlat)                                                      mo_vectri.f90      mo_vectri.f90

! == Hydrology ==

! rwaterpond(nlon,nlat)         Y                 Y            Y                      mo_vectri.f90      mo_interface.f90      mo_interface.f90
! rwaterurbn(nlon,nlat)         Y                 Y            Y                      mo_vectri.f90      mo_interface.f90      mo_interface.f90
! rwaterperm(nlon,nlat)         Y                 Y            Y(DEFAULT only)        mo_vectri.f90      mo_interface.f90      mo_ncdf_tools.f90/mo_interface.f90
! rsoilinfil(nlon,nlat)         Y                 Y            Y                      mo_vectri.f90      mo_interface.f90      mo_interface.f90
!
! == SIT ========

!
!
!
!-----------------------------------------------------------------------------------------------

! Default output if VECTRI is active

logical :: out_vect   =.true.        ! Vector density
logical :: out_vecinfc=.true.        ! Infective vector density
logical :: out_larv   =.false.       ! Larval density
logical :: out_wpond  =.true.        ! Pond fraction
logical :: out_wurbn  =.true.        ! Urban fraction
logical :: out_wperm  =.true.        ! Permanent fraction

!=============================================

INTEGER, PARAMETER :: slen=100                   ! mo_vectri.f90

! Advection scheme 
integer :: nnumeric = 2                          ! mo_control.f90
!
integer :: iounit = 7                            ! mo_interface.f90

! resolution of larvae development
integer, parameter :: nlarv=25                   ! mo_control.f90
! resolution of vector parasite development
!integer, parameter :: ninfv=25                   ! mo_control.f90 --> Moved to AB constants file as needed in agents methods
!
!
real :: rvect_min=1.e-4                          ! mo_control.f90
!
!
! Vector ================================================
real, allocatable :: rlarv(:,:) ! (0:nlarv,nlon*nlat)
!real, allocatable :: rvect(:,:) ! (0:ninfv,nlon*nlat) --> Moved to AB constants file as needed in agent methods

real, allocatable :: rmasslarv(:)     ! mass of larvae (0:nlarv)

real, allocatable :: rbitezoo(:)      ! (nlon*nlat)
real, allocatable :: rzoophilic(:)    ! (nlon*nlat)


! 2d arrays =======================================
!real, allocatable :: point_rain(:)           ! (nlon*nlat)
!real, allocatable :: point_t2m(:)            ! (nlon*nlat)

!
real, allocatable :: zsurvp_larv(:)           ! (0:nlarv)

real, allocatable :: zvecinfc(:)              ! (nlon*nlat)
 
real, allocatable :: zvect_density(:)       ! (nlon*nlat)
real, allocatable :: zvect_one_d_density(:) ! (nlon*nlat)

real :: zgonof !
!===========================================================


! Hydrology ================================================
real, allocatable :: rwaterpond(:)  ! nlat*nlon  ! temporary ponds        
real, allocatable :: rwaterperm(:)  ! nlat*nlon  ! permanent features, lakes rivers etc        
real, allocatable :: rwaterurbn(:)  ! nlat*nlon  ! urban water availiability (gutters, tires, cans etc)
real, allocatable :: rsoilinfil(:)  ! nlat*nlon       


! == Pointers



! data structure for climate data, soil and hydrological data
!
TYPE datafld
  INTEGER :: varid  ! netcdf identifier of field
  CHARACTER(LEN=slen) :: varname ! internal var name
  CHARACTER(LEN=slen) :: ncname ! nc field name
  REAL :: miss=-999
  REAL :: infil=-999
  REAL, ALLOCATABLE :: vals(:)  ! (nlon*nlat)
END TYPE datafld

! =======================================================
TYPE(datafld),SAVE,DIMENSION(3):: soil= [ &
&   datafld(-99,"clay","GLDAS_soilfraction_clay",-999), &
&   datafld(-99,"silt","GLDAS_soilfraction_silt",-999), &
&   datafld(-99,"sand","GLDAS_soilfraction_sand",-999)  ]

!==
   !
   CONTAINS
       !
       !-------------------------------------------------
       !
        subroutine init_vectri(pop_dens,mask_pop,nlon,nlat)
           implicit none

           integer, intent(in) :: nlon, nlat
           real, allocatable, intent(in) :: pop_dens(:) !(nxy)     
           logical, allocatable, intent(in) :: mask_pop(:) !(nxy)


           ! Local use only
           integer :: ixy, i, is

           npud_scheme=npud_scheme_default

           allocate(nbites(nlon*nlat))
           nbites(:) = 0.

           allocate(m_0(nlon*nlat))
           allocate(m_1(nlon*nlat))
           m_0(:) = 0.
           m_1(:) = 0.

           !----- Larva biomass -------------------
           !=
             allocate(rmasslarv(0:nlarv))
             ! mass relationship of larvae - we assume a stage 4 size as Bomblies and 
             ! we will assume a linear mass increase with age unless find other reference 
             ! this linear growth rate is very close to that assumed by Bomblies.   
             do i=0,nlarv
                rmasslarv(i)=float(i)*rmasslarv_stage4/float(nlarv)
             end do
           !=
           !------ Vector arrays ------------------
           !=
             allocate(rvect(0:ninfv,nlon*nlat))
             rvect(:,:) = 0.

             where(mask_pop) rvect(0,:) = 100*rhost_infect_init*rvect_min
             where(mask_pop) rvect(ninfv,:)=10*rhost_infect_init*rvect_min

             allocate(zvect_density(nlon*nlat))
             allocate(zvect_one_d_density(nlon*nlat))
             allocate(zvecinfc(nlon*nlat))

             zvect_density(:)=SUM(rvect, DIM=1) ! total vector number = vector density   

             !-- Larva
             allocate(rlarv(0:nlarv,nlon*nlat))
             rlarv(:,:) = 0.
             
             allocate(zsurvp_larv(0:nlarv))
             zsurvp_larv(:) = 1.
            !------------------------------

             allocate(rbitezoo(nlon*nlat))
             allocate(rzoophilic(nlon*nlat))
             
             rbitezoo(:)   = 0.
             rzoophilic(:) = 0.

             allocate(rgonof(nlon*nlat))
             rgonof(:) = 0.
            
          !=
          !------ Hydro/Carrying capacity ---------
          !=
            allocate(rwaterpond(nlon*nlat))   ! diagnostic 
            allocate(rwaterperm(nlon*nlat))   ! diagnostic
            allocate(rwaterurbn(nlon*nlat))   ! diagnostic
            allocate(rsoilinfil(nlon*nlat))   ! diagnostic --> Needed for the pond scheme

            rwaterpond(:) = 0.
            rwaterurbn(:) = 0.
            rwaterperm(:) = 0.

            where(mask_pop) rwaterpond(:) = wpond_min
            where(mask_pop) rwaterperm(:) = wperm_default
            where(mask_pop) rwaterurbn(:) = log(pop_dens(:)/wurbn_tau+1.0)*wurbn_sf   
            
           ! rwaterpond = 0.
           ! rwaterperm=max(rwaterperm,wperm_default)
          !=
          !---- Soil --------------
          !=
            do is=1,SIZE(soil)   
               allocate(soil(is)%vals(nlon*nlat))
            end do

            do i=1,SIZE(soil)
                soil(i)%vals(:)=1./3.
            end do   
            
            ! initialize infiltration rates 
            DO is=1,SIZE(soil)
               SELECT CASE(soil(is)%varname)
               CASE("clay")
                  soil(is)%infil=wpond_infil_clay
               CASE("silt")
                  soil(is)%infil=wpond_infil_silt
               CASE("sand")
                  soil(is)%infil=wpond_infil_sand
               END SELECT
            ENDDO
            rsoilinfil(:)=0.0
            DO is=1,SIZE(soil)
               DO ixy=1,nlon*nlat
                 rsoilinfil(ixy)=rsoilinfil(ixy)+ &
                   & soil(is)%vals(ixy)*soil(is)%infil
                 !   soil frac           *infil val
               ENDDO
            ENDDO
         !=
         !
        end subroutine init_vectri
        !
        !
        !
        subroutine source_integrate_VECTRI(ixy,nbites,npeop,rvect,rlarv,rrain,rtemp,rpopdensity,mask_pop,dt, &
                                                zvecinfc, zvect_density, zvect_one_d_density, zgonof)

               !
               ! This subroutine wraps VECTRI's vector methods
               !

               ! Input from used modules
               
               ! mo_constants.F90 (VECTRI)
               ! mo_const.F90 (AB)
               ! mo_vectri.F90 (AB)
               !
                implicit none

                real, intent(in) :: dt                       ! Time step
                integer, intent(in) :: ixy                   ! Grid point

                ! Disease
                integer, allocatable, intent(in) :: nbites(:) ! (nlon*nlat) Number of infective bites
                integer, allocatable, intent(in) :: npeop(:)  ! (nlon*nlat)
                
                ! Vectors
                real, allocatable, intent(inout) :: rvect(:,:)    ! (0:ninfv,nlon*nlat) Adult vector density
                real, allocatable, intent(inout) :: rlarv(:,:)    ! (0:nlarv,nlon*nlat)
                real, intent(inout) :: zgonof

               ! Climate 
                real, intent(in) :: rrain, rtemp     ! (:, t=it) --> (nlat*nlon)
                
                ! Host
                real, allocatable, intent(in) :: rpopdensity(:) !(nlon*nlat)
                logical, allocatable, intent(in) :: mask_pop(:)      ! (nlon*nlat)
                ! Local use only

                ! "z" variables

                ! == Vector
                
                real :: sum_egg, zdel, zfac, zlarvmaturef, zmasslarv, zsurvp_vec
                real, allocatable :: zvect_density(:), zvect_one_d_density(:) !(nlon*nlat)

                ! == Climate
                real :: zrain         ! Day rainfall at given grid point = rrain(ixy) with safety limits 
                real :: ztemp         ! Day temperature (mix of indoor and outdoor) at given grid point ~ rtemp(ixy) 
                real :: ztempindoor   ! Parameter 
                real :: ztempwater    ! Temperature of water at given grid point ~ t2m(ixy) + offsetztempwater
                
                ! == Disease
                real :: zprobhost2vect, zsporof
                real, allocatable :: zvecinfc(:)   !(nlon*nlat)

                !=========================================================
                    ! Safety check and temporary diagnostics
                    !
                    call safe_diag(zvect_density,zvect_one_d_density,zvecinfc,rlarv,rvect,rvect_min,ninfv,&
                                    rpopdensity,mask_pop,rbitezoo,rzoophilic,dt,ixy) 

                    !zmasslarv=SUM(rlarv(:,ixy)*rmasslarv(:))  ! Should we move this to where it is actually used?
                    !
                    !--------------------------------------------------
                    ! Meteorological data
                    !
                    call meteo_point(ixy,zrain,rrain,ztempindoor,ztempwater,ztemp,rtemp) 
                    !
                    !---------------------------------------------------------------------
                    ! Gonotrophic velocity
                    !
                    call gono(ztemp,zgonof,dt) 
                    !            
                    !---------------------
                    ! Sporogonic cycle
                    !---------------------
                    !
                    zprobhost2vect = dble(nbites(ixy))/npeop(ixy)
                    ! 
                    call sporo(ixy,ztemp,zprobhost2vect,zgonof,rvect,zsporof,zdel,nnumeric,ninfv,dt,iounit)
                    !
                    !----------------------------------------------------------------------------------------
                    ! Vector temperature-dependent survival scheme
                    !
                    call vec_temp_surv(ixy,rvect,ztemp,zsurvp_vec,dt)
                    !
                    !--------------------------------------------------
                    ! Vector oviposition
                    !
                    zfac = 1. !-- To be changed with SIT coupling 
                    call vec_ovi(ixy,ninfv,zfac,zgonof,rvect,rlarv,sum_egg)
                    !
                    !--------------------------------------------------------
                    ! Pond model
                    !
                    call pond(ixy,dt,iounit,zrain,rwaterpond,rsoilinfil)
                    !
                    !-----------------------------------------------------
                    ! Larvae maturation - larvae progression
                    !
                    call larv_dev(ixy,dt,iounit,ztempwater,zlarvmaturef,rlarv,nlarv,nnumeric) 
                    !
                    !--------------------------------------------------------------------------
                    ! Larvae mortality
                    ! 
                    call larv_mort(ixy,dt,zsurvp_larv,ztempwater,zmasslarv,zrain, & 
                               rwaterpond,rwaterperm,rwaterurbn,rlarv,rmasslarv,nlarv)
                    !     
                    !-----------------------------------------------------------------
                    ! Larvae hatching
                    !
                    call larv_hatch(ixy,rlarv,rvect,nlarv)
                    !
                    !---------------------------------------
           


                end subroutine source_integrate_VECTRI
                !
!===============
end MODULE mo_vectri





