MODULE mo_vectri

!
! Adrian M. Tompkins (tompkins@ictp.it)           2025
! Miguel Garrido Zornoza (mgarrizoraca@gmail.com) 2025
!


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


! Advection scheme 
integer :: nnumeric = 2                          ! mo_control.f90
!
integer :: iounit = 7                            ! mo_interface.f90

! resolution of larvae development
integer, parameter :: nlarv=25                   ! mo_control.f90
! resolution of vector parasite development
integer, parameter :: ninfv=25                   ! mo_control.f90
!
!
real :: rvect_min=1.e-4                          ! mo_control.f90
!
!
real, allocatable :: rlarv(:,:,:) ! (0:nlarv,nlon,nlat)
real, allocatable :: rvect(:,:,:) ! (0:ninfv,nlon,nlat)

real, allocatable :: rmasslarv(:)     ! mass of larvae (0:nlarv)

real, allocatable :: rbitezoo(:,:)      ! (nlon,nlat)
real, allocatable :: rzoophilic(:,:)    ! (nlon,nlat)

real, allocatable :: zsurvp_larv(:)


real, allocatable :: rwaterpond(:,:)  ! nlat,nlon  ! temporary ponds        
real, allocatable :: rwaterperm(:,:)  ! nlat,nlon  ! permanent features, lakes rivers etc        
real, allocatable :: rwaterurbn(:,:)  ! nlat,nlon  ! urban water availiability (gutters, tires, cans etc)
real, allocatable :: rsoilinfil(:,:)  ! nlat,nlon       

!===========================================================
allocate(rmasslarv(0:nlarv))
! mass relationship of larvae - we assume a stage 4 size as Bomblies and 
! we will assume a linear mass increase with age unless find other reference 
! this linear growth rate is very close to that assumed by Bomblies.   
do ix=0,nlarv
   rmasslarv(ix)=float(ix)*rmasslarv_stage4/float(nlarv)
end do
!===========================================================

allocate(rvect(0:ninfv,nlon,nlat))
allocate(rlarv(0:nlarv,nlon,nlat))

rvect(0,:,:)=100*rhost_infect_init*rvect_min             ! fixed density of vectors
rvect(ninfv,:,:)=10*rhost_infect_init*rvect_min          ! fixed density of vectors
rlarv(:,:,:) = 0.

allocate(zsurvp_larv(0:nlarv))

rsurvp_larv(:) = 1.

allocate(rbitezoo(nlon,nlat))
allocate(rzoophilic(nlon,nlat))

rbitezoo(:,:)   = 0.
rzoophilic(:,:) = 0.

allocate(rwaterpond(nlon,nlat))   ! diagnostic 
allocate(rwaterperm(nlon,nlat))   ! diagnostic
allocate(rwaterurbn(nlon,nlat))   ! diagnostic
allocate(rsoilinfil(nlon,nlat))   ! diagnostic --> Needed for the pond scheme


rwaterpond(:,:) = wpond_min
rwaterperm(:,:) = wperm_default
rwaterurbn(:,:  = 0.0


! data structure for climate data, soil and hydrological data
!
TYPE datafld
  INTEGER :: varid  ! netcdf identifier of field
  CHARACTER(LEN=slen) :: varname ! internal var name
  CHARACTER(LEN=slen) :: ncname ! nc field name
  REAL :: miss=-999
  REAL :: infil=-999
  REAL, ALLOCATABLE :: vals(:,:)
END TYPE datafld

! =======================================================
TYPE(datafld),SAVE,DIMENSION(3):: soil= [ &
&   datafld(-99,"clay","GLDAS_soilfraction_clay",-999), &
&   datafld(-99,"silt","GLDAS_soilfraction_silt",-999), &
&   datafld(-99,"sand","GLDAS_soilfraction_sand",-999)  ]

do i=1,SIZE(soil)
    soil(i)%vals(:,:)=1./3.
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
rsoilinfil(:,:)=0.0
DO is=1,SIZE(soil)
   DO iy=1,nlat
      DO ix=1,nlon
         rsoilinfil(ix,iy)=rsoilinfil(ix,iy)+ &
           & soil(is)%vals(ix,iy)*soil(is)%infil
         !   soil frac           *infil val
      ENDDO
   ENDDO
ENDDO
! ============================================
forall(iy=1:nlat,ix=1:nlon,mask_pop(ix,iy))
    rwaterurbn(ix,iy)=log(pop_dens(ix,iy)/wurbn_tau+1.0)*wurbn_sf   
end forall

rwaterpond = 0.
rwaterperm=max(rwaterperm,wperm_default)
! ============================================




!==
   implicit none
   !
   CONTAINS
       !
       !-------------------------------------------------
       !
        subroutine init_vectri()

           ! call allocate_vectri_fields()

           ! call init_vectri_field()



        end subroutine init_vectri
        !
        !
        !
        subroutine source_integrate_VECTRI(ix, iy,nbites,V,L)

               !
               ! This subroutine ...
               !

               ! Input from used modules
               
               ! mo_constants.F90 (VECTRI)
               ! mo_const.F90 (AB)
               ! mo_vectri.F90 (AB)
               !
                implicit none

                integer, intent(in) :: ix, iy                   ! Grid point
                integer, allocatable, intent(in) :: nbites(:,:) ! (nx, ny) Number of infective bites
                
                real, allocatable, intent(in) :: rvect(:,:,:)    ! V(1:ninfv, nx, nxy) Adult vector density
                real, allocatable, intent(in) :: rlarv(:,:,:)    ! L(0:nlarv,nlon,nlat)
                real, allocatable, intent(in) :: rmasslarv(:)    ! M_L(0:nlarv)  


                    ! Safety check and temporary diagnostics
                    !
                    call safe_diag(zvect_density,zvect_one_d_density,zvecinfc,rlarv,rvect,rvect_min,ninfv,&
                                    rpopdensity,rbitezoo,rzoophilic,dt) 
                    !
                    !--------------------------------------------------
                    ! Meteorological data
                    !
                    call meteo_point(ix,iy,zrain,rrain,ztempindoor,ztempwater,ztemp,rtemp) 
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
                    call sporo(ix,iy,ztemp,zprobhost2vect,zgonof,rvect,zsporof,zdel,nnumeric,ninfv,dt,iounit)
                    !
                    !----------------------------------------------------------------------------------------
                    ! Vector temperature-dependent survival scheme
                    !
                    call vec_temp_surv(ix,iy,rvect,ztemp,zsurvp_vec,dt)
                    !
                    !--------------------------------------------------
                    ! Vector oviposition
                    !
                    zfac = 1. !-- To be changed with SIT coupling 
                    call vec_ovi(ix,iy,ninfv,zfac,zgonof,rvect,rlarv,sum_egg)
                    !
                    !--------------------------------------------------------
                    ! Pond model
                    !
                    call pond(ix,iy,dt,iounit,zrain,rwaterpond,rsoilinfil)
                    !
                    !-----------------------------------------------------
                    ! Larvae maturation - larvae progression
                    !
                    !
                    call larv_dev(ix,iy,dt,iounit,ztempwater,zlarvmaturef,rlarv,nlarv,nnumeric) ! --AB--
                    !
                    !--------------------------------------------------------------------------
                    ! Larvae mortality
                    ! 
                    call larv_mort(ix,iy,dt,zsurvp_larv,ztempwater,zmasslarv,zrain, & 
                               rwaterpond,rwaterperm,rwaterurbn,rlarv,rmasslarv,nlarv)
                    !     
                    !-----------------------------------------------------------------
                    ! Larvae hatching
                    !
                    call larv_hatch(ix,iy,rlarv,rvect,nlarv)
                    !
                    !---------------------------------------
           


                end subroutine source_integrate_VECTRI
                !
!===============
end MODULE mo_vectri





