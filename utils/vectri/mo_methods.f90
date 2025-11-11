! --AB-- 
MODULE mo_methods

! This module includes safety checks and derivation of diagnostics (I) as
! well as methods on vectors (II) and serves as coupling between VECTRI 
! and ICTP's agent-based (AB) model.
!
!===
    ! (I) ----------------------------------------------------------------
    ! Safety &
    ! Diagnostics  --> safe_diag    (vector stats)
    ! Point arrays --> meteo_point  (meteorological data stats)


    ! (II)
    ! 3. Gonotrophic cycle velocity
    ! 4. Sporogonic cycle
    ! (5.  Gonotrophic cycle) --> Not resolved
    ! 6. Vector temperature-dependent survival
    ! 7. Vector Oviposition
    ! 8. Pond model
    ! (9. Larvae maturation - limitation of resources)
    ! 10. Larvae maturation - larvae progression
    ! 12. Larvae hatching
    !---------------------------------------------------------------------
    
    ! To Do:
    ! - Include interventions (SIT methods are still in vectri.f90)
!===
! 
!

! VECTRI modules
USE mo_advect
USE mo_constants
!USE mo_interface.F90
!USE mo_control --> For the coupling the idea is to make things independent of the mo_control module,
!                   which is program-specific (VECTRI or AB). This module is loaded in the main file and is
!                   where the subroutines of the mo_methods module are actually called.
!
!
!==
   implicit none
   !
   CONTAINS
       !
       !-------------------------------------------------
        !
        !
        !============== (I) =================
        !
        subroutine safe_diag(zvect_density,zvect_one_d_density,zvecinfc,rlarv,rvect,rvect_min,ninfv,&
          rpopdensity,mask_pop,rbitezoo,rzoophilic,dt,ixy)
        !
        ! 
        ! Input from used modules: 
        !
        ! mo_advect.F90 : x
        ! mo_constants.F90 : rzoophilic_tau, rbiteratio
        ! mo_control.F90 : (rvect_min, ninfv, dt -> now directly fed to the subroutine)
        ! mo_interface.F90: x
        !
        !=
          implicit none
          !
          INTEGER, intent(in)  :: ixy     ! Grid point
          REAL, intent(in)  :: dt      ! Time step
          REAL, intent(in)  :: rvect_min
          INTEGER, intent(in) :: ninfv
          REAL, allocatable, intent(inout) :: rbitezoo(:)      ! (nlon*nlat)
          REAL, allocatable, intent(inout) :: rzoophilic(:)    ! (nlon*nlat)
          REAL, allocatable, intent(in)    :: rpopdensity(:)   ! (nlon*nlat)
          LOGICAL, allocatable, intent(in) :: mask_pop(:)      ! (nlon*nlat)
          REAL, allocatable, intent(inout) :: zvecinfc(:)      ! (nlon*nlat)
          REAL, allocatable, intent(inout) :: zvect_density(:) ! (nlon*nlat)
          REAL, allocatable, intent(inout) :: zvect_one_d_density(:) ! (nlon*nlat)
          REAL, allocatable, intent(inout) :: rvect(:,:)     ! (0:ninfv,nlon*nlat)
          REAL, allocatable, intent(inout) :: rlarv(:,:)     ! (0:nlarv,nlon*nlat)

          !------------------------------------------------
          ! Safety  
          !------------------------------------------------
          rlarv(:,ixy)=MAX(rlarv(:,ixy),0.0)
          rvect(:,ixy)=MAX(rvect(:,ixy),0.0)
       !
       !   ! copy rvect for diffusion calculation
       !   
       !   !------------------------------------------------
       !   ! Temporary diagnostics
       !   !------------------------------------------------
       !   
          zvect_density(ixy)=SUM(rvect(:,ixy)) ! total vector number = vector density    
          zvect_one_d_density(ixy)=1.0/MAX(zvect_density(ixy),reps)
       !   
          zvecinfc(ixy)=rvect(ninfv,ixy)*zvect_one_d_density(ixy) ! CSPR for malaria
        !  zvecinfc(ixy)=MAX(rvect(ninfv,ixy)*zvect_one_d_density(ixy),rvect_min) ! CSPR for malaria
       !        !   ! zoophilic rates - well actually is anthropophilic rate.
       !   WHERE (rpopdensity(:)>=0.0) &
       !        & rzoophilic=1.0-(1.0-rzoophilic_min)*EXP(-rpopdensity(:)/rzoophilic_tau)
       !   rbitezoo(:)=1.0-(1.0-rbiteratio*rzoophilic(:))*dt ! product useful 
       
           if (mask_pop(ixy)) then
              ! zoophilic rates - well actually is anthropophilic rate.
              rzoophilic(ixy)=1.0-(1.0-rzoophilic_min*EXP(-rpopdensity(ixy)/rzoophilic_tau))
              !
              !rvect(0,ixy)=MAX(rvect(0,ixy),rvect_min)
              rlarv(0,ixy)=MAX(rlarv(0,ixy),rvect_min)
              !
           end if

           rbitezoo(ixy)=1.0-(1.0-rbiteratio*rzoophilic(ixy))*dt ! product useful 


        end subroutine safe_diag



        subroutine meteo_point(ixy,zrain,rrain,ztempindoor,ztempwater,ztemp,rtemp)

        ! 
        ! Input from used modules: 
        !
        ! mo_advect.F90 : x
        ! mo_constants.F90 : rwater_tempoffset, rbeta_indoor
        ! mo_control.F90 : x
        ! mo_interface.F90: x
        !
        !=
          implicit none
          !
          INTEGER, intent(in) :: ixy       ! Grid point
          REAL, intent(out)   :: zrain        ! Day rainfall at given grid point = rrain(ixy) with safety limits 
          REAL, intent(out)   :: ztemp        ! Air temperature 
          REAL, intent(out)   :: ztempwater   ! Temperature of water at given grid point ~ t2m(ixy) + offset
          REAL, intent(inout) :: ztempindoor
          REAL, intent(in) :: rrain, rtemp ! (nlon*nlat)

          zrain=MIN(MAX(rrain,0.0),200.0)  ! 1 day rainfall, with safety limits applied.

          ! indoor temperature - after Lunde et al. Malaria Journal 2013, 12:28
          ztempindoor=10.33+0.58*rtemp
 
          ! water temperature 
          ztempwater=rtemp+rwater_tempoffset ! water temperature
 
          ! temperature experience by vector is mix of indoor and outdoor 
          ! temperature on a daily timestep
          ztemp=rbeta_indoor*ztempindoor+(1.0-rbeta_indoor)*rtemp
        !=
        !
        end subroutine meteo_point
        !
        !
        !============== (II) =================
        !
        subroutine sporo(ixy,ztemp,zprobhost2vect,zgonof,rvect,zsporof,zdel, &
                                nnumeric, ninfv, dt, iounit)
        ! 
        ! Input from used modules: rbiteratio, dsporo, rtsporo, 
        !                          reps, ninfv, dt
        !
        ! mo_advect.F90 : x
        ! mo_constants.F90 : rbiteratio, dsporo, rtsporo, reps, nsporo_scheme
        ! mo_control.F90 : x (ninfv, dt, nnumeric -> now directly fed to the subroutine)
        ! mo_interface.F90 : x (iounit -> now as input)
        !
        !=
          implicit none
          !
          INTEGER, intent(in) :: ixy         ! Grid point
          INTEGER, intent(in) :: iounit, ninfv, nnumeric   !
          REAL, intent(in)    :: dt             ! Time step
          REAL, intent(in)    :: ztemp          ! Air temperature 
          REAL, intent(in)    :: zprobhost2vect ! Probability of host to vector transmission of parasite
          REAL, intent(inout) :: zgonof         ! 
          REAL, intent(inout) :: zdel           !
          REAL, allocatable, intent(inout) :: rvect(:,:) !(0:ninfv,nlon*nlat)
          REAL, intent(out)   :: zsporof        ! Fractional development
          !
          !
          ! --------------- 4. Sporogonic cycle ---------------------------------------
          ! 4.1 Transmission of the parasite
              !      
              ! - From v1.4 bug correct - rbiteratio added to transmission probability
              ! - From v1.8 - gonof added as gonotrophic cycle resolution removed.
              ! - Calculate the density of "newly-emerged" population finding a blood meal
              !   AND getting infected. This is weighted by the fraction of
              !   "newly-emerged"/never infected vectors that just laid eggs (zgonof) and 
              !   are thus assumed to be searching for a new blood meal.
              zdel=rbiteratio*zprobhost2vect*zgonof*rvect(0,ixy) 
              rvect(0,ixy)=rvect(0,ixy)-zdel   
              rvect(1,ixy)=rvect(1,ixy)+zdel   

          ! 4.2 Development of the parasite 
              !
              ! - Degree day concept of Detinova (1962) or exponential EIPs
              ! - We here calculate the "advected" fractional developement, f \in [0,1]

              SELECT CASE(nsporo_scheme)
              CASE(1) ! degree day concept of Detinova (1962) ! Anopheles
                zsporof=dt*(ztemp-rtsporo)/dsporo
              CASE(2) ! dengue scheme (exponential EIP(T))
                zsporof=dt*1/(1.03*(4+EXP(5.15-0.123*ztemp))) ! Ae. albopictus
              CASE(3) ! dengue scheme (exponential EIP(T))
                zsporof=dt*1/(1.00*(4+EXP(5.15-0.123*ztemp))) ! Ae. aegypti
              CASE DEFAULT
                STOP 'invalid sporogonic cycle scheme'
              END SELECT
              zsporof=MIN(MAX(0.0,zsporof),1.0)
              !
              ! Advection 
              IF (zsporof>reps) THEN
                ! - Box 0 is left behind (not advected) as this represents non-infected vectors
                ! - ninfv is an absorbing state (no parasite clearance
                !   in vector as life expectancy is too low to be worth 
                !   resolving)
                CALL advection(0.0,zsporof,rvect(0:ninfv,ixy),ninfv,nnumeric,iounit)
              ENDIF
              !
        end subroutine sporo
        !  
        !
        subroutine gono(ztemp,zgonof,dt)
        !
        ! Input from used modules:
        !
        ! mo_advect.F90 : x
        ! mo_constants.F90 : dsgono, rtgono
        ! mo_control.F90 : x (dt -> now directly fed to the subroutine)
        ! mo_interface.F90: 
        !
        !
          implicit none
          REAL, intent(in)    :: dt      ! Time step
          REAL, intent(in)    :: ztemp   ! 
          REAL, intent(inout) :: zgonof  !
          !=

            ! --------------- 3. Gonotrophic cycle velocity ------------------------------
              ! - Calculate fraction of gonotrophic cycle in a day for 
              !   vector oviposition and sporo subroutines using degree 
              !   day concept of Detinova (1962)

              zgonof=dt*(ztemp-rtgono)/dgono
              zgonof=MIN(MAX(0.0,zgonof),1.0)

            ! --------------- 5. Gonotrophic cycle ---------------------------------------
              ! - From v1.8 no longer explicitly resolved. 
              
          !=
          !
        end subroutine gono
        !
        !
        !
        subroutine vec_temp_surv(ixy,rvect,ztemp,zsurvp_vec,dt)

        ! 
        ! Input from used modules: 
        !
        ! mo_advect.F90 : x
        ! mo_constants.F90 : rmar1, rmar2, rtvecsurvmin, rtvecsurvmax, nsurvival_scheme
        !                    rvecsurv
        ! mo_control.F90 : x (dt -> now directly fed to the subroutine)
        ! mo_interface.F90: 
        !
        !=
          implicit none
          INTEGER, intent(in) :: ixy
          REAL, intent(in)  :: dt      ! Time step
          REAL, intent(in)  :: ztemp      ! Air temperature
          REAL, intent(out) :: zsurvp_vec ! Survival probability
          REAL, allocatable, intent(inout) :: rvect(:,:) ! (0:ninfv,nlon*nlat)



          ! --------------- 6. Vector temperature dependent survival ---------------------------------------
          ! 6.1 Vector temperature dependent survival
              !
              ! See PhD Thesis of Ermert 2010 for I-III
              !
              ! 1) Anopheles Martins I
              ! 2) Anopheles Martins II 
              ! 3) Anopheles Bayoh Scheme
              ! 4) Aedes albopictus (Metelmann scheme [ref]: https://doi.org/10.1098/rsif.2018.0761)
              ! 5) Aedes aegypti (xxx scheme [ref]: (missing))
              !
              !-----------------------------------------

              IF (ztemp>rtvecsurvmin.AND.ztemp<rtvecsurvmax) THEN

                 SELECT CASE(nsurvival_scheme)
                 CASE(1) ! martins I
                    zsurvp_vec=rmar1(0) + rmar1(1)*ztemp + rmar1(2)*ztemp**2
                 CASE(2) ! martins II
                    zsurvp_vec=EXP(-1.0/(rmar2(0)+rmar2(1)*ztemp+rmar2(2)*ztemp**2))
                 CASE(3) ! Bayoh scheme 
                    zsurvp_vec= -2.123e-7*ztemp**5 &
                         & +1.951e-5*ztemp**4 &
                         & -6.394e-4*ztemp**3 &
                         & +8.217e-3*ztemp**2 &
                         & -1.865e-2*ztemp + 7.238e-1
                 CASE(4) ! Metelmann scheme 
                    zsurvp_vec= 0.677*EXP(-0.5*((ztemp-20.9)/13.2)**6)*ztemp**0.1 
                 CASE(5) ! Caldwell scheme (rescaled to range between 0-0.9)
                    zsurvp_vec= (-1.48E-1 * (ztemp-9.16) * (ztemp-37.73))/33.35
                 CASE DEFAULT
                    STOP 'invalid survival scheme'
                 END SELECT

                 ! from v1.3.5 base mortality rate added
                 zsurvp_vec=zsurvp_vec*rvecsurv
                 zsurvp_vec=MIN(MAX(rvecsurv_min,zsurvp_vec),1.0)

              ELSE
                 zsurvp_vec=rvecsurv_min ! small background probability for niche  
              ENDIF

              ! Apply the temperature-driven mortality step

              rvect(:,ixy)=zsurvp_vec*rvect(:,ixy)*dt


        end subroutine vec_temp_surv
        !
        !
        !
        subroutine vec_ovi(ixy,ninfv,zfac,zgonof,rvect,rlarv,sum_egg)
        
        ! 
        ! Input from used modules: 
        !
        ! mo_advect.F90 : x
        ! mo_constants.F90 : neggmn
        ! mo_control.F90 : x (ninfv -> now directly fed to the subroutine)
        ! mo_interface.F90: 
        !
        !=
          implicit none
          !
          INTEGER, intent(in) :: ixy,ninfv
          REAL, intent(in)    :: zfac
          REAL, intent(in)    :: zgonof
          REAL, intent(inout) :: sum_egg
          REAL, allocatable, intent(in) :: rvect(:,:) ! (0:ninfv,nlon*nlat)
          REAL, allocatable, intent(inout) :: rlarv(:,:) ! (0:nlarv,nlon*nlat)
          !
          ! Local use only
          REAL :: znewegg
          INTEGER :: iinfv
          !
          ! --------------- 7. Vector Oviposition ---------------------------------------
              ! - From v1.10 added factor to reduce eggs with SIT females present (zfac)
              !-----------------------------------------------------------
              !
              sum_egg=0
              DO iinfv=0,ninfv
                 znewegg=neggmn*zfac*zgonof*rvect(iinfv,ixy)
                 rlarv(0,ixy)=rlarv(0,ixy) + znewegg
                 sum_egg = sum_egg + znewegg
                 
              ENDDO
              !
        end subroutine vec_ovi
        !
        !
        !
        subroutine pond(ixy,dt,iounit,zrain,rwaterpond,rsoilinfil)
        ! 
        ! Input from used modules: 
        !
        ! mo_advect.F90 : x
        ! mo_constants.F90 : npud_scheme, wpond_rate, wpond_max, wpond_evap, wpond_shapep2
        !                    wpond_depthref, wpond_ref, wpond_S
        ! mo_control.F90 : x (dt -> now directly fed to the subroutine)
        ! mo_interface.F90 : x (wpond_S -> moved to mo_constants.F90, iounit -> now as input)
        !
        !=
          implicit none
          !
          INTEGER, intent(in) :: ixy   ! Grid point
          INTEGER, intent(in) :: iounit   !
          REAL, intent(in)    :: dt       ! Time step
          REAL, intent(in)    :: zrain    ! Day rainfall at given grid point = rrain(ixy) with safety limits 
          REAL, allocatable, intent(in)    :: rsoilinfil(:) ! Soil infiltration (nlon*nlat)
          REAL, allocatable, intent(inout) :: rwaterpond(:) ! Temporary ponds (nlon*nlat)
          !
          ! Local use only
          REAL :: zpud1, zpud2, zrunoff  ! Pond variables
          REAL :: zguess
          !
          ! --------------- 8. Pond model ---------------------------------------
          SELECT CASE(npud_scheme)
              CASE(0)
                ! external scheme do nothing here as ponding read in from external data file
                CONTINUE

              ! Simple Hydro scheme described in Tompkins and Ermert (2013)
              CASE(1)
                zpud1=wpond_rate*dt
                rwaterpond(ixy)=(rwaterpond(ixy)+zpud1*zrain*wpond_max)/ &
                     & (1.0+zpud1*(zrain+wpond_evap+rsoilinfil(ixy)))
               
              !--------------------------------------------------------------------------
              ! Revised hydrology:
              ! Implicit scheme described in 
              ! - Asare et al. 2016a (Geospatial Health)
              ! - Asare, Tompkins and Bomblies PLOS One 2016
              ! Scheme includes shape factor for pond geometry and initial abstraction.
              ! The latter term is important to prevent ponding after light rain events. 
              !
              ! dw/dt = K w^(-p/2) (fQ - w(E+fI))
              !         K: pond geometry scale factor (related to S0 and h0 in geometry model)
              !         p: pond geometry power factor (0.5-2 temporary ponds, 3-5 lakes)
              !         f: proportion of maximum pond area factor 1-w/w_max
              !         Q: run off - calculated from SCS formula Q=(P-0.2S)^2/(P+0.8S)
              !         E: evaporation from ponds
              !         I: maxmimum infiltration rate from ponds
              !-----------------------------------------
              CASE(2) 
                zrunoff=MAX(0.0,zrain-0.2*wpond_S)**2/(zrain+0.8*wpond_S)  
                zrunoff=Max(zrunoff,0.0)

                zpud1=(2.0*dt)/(wpond_shapep2*wpond_depthref)!2*Dt/(p*refernce water depth)
                zpud2=(2.*dt*wpond_ref**(wpond_shapep2/2.))/ &
                & (wpond_shapep2*wpond_depthref)
                !2*wref^(p/2)/p*href
 
                ! first guess solution
                zguess=(rwaterpond(ixy)+zpud1*(zrunoff*wpond_max))/ &
                & (1.0+zpud1*(zrunoff+wpond_evap-zrain+(wpond_ref*zrain)/wpond_max+&
                & (wpond_ref*rsoilinfil(ixy))/wpond_max))

                ! solution
                rwaterpond(ixy)=(rwaterpond(ixy)+zpud2*(zguess** &
                & (-wpond_shapep2/2.)*zrunoff*wpond_max))/ &
                & (1.0+zpud2*zguess**(-wpond_shapep2/2.)* &
                & (zrunoff+wpond_evap-zrain+ &
                & (zguess*zrain)/wpond_max+ &
                & (zguess*rsoilinfil(ixy))/wpond_max))

              CASE DEFAULT
                WRITE(iounit,*)'no default option for wpond - please set npud_scheme=0,1,2'
                STOP
              END SELECT
              
              ! breeding water fraction is the sum of temporary ponds and permanent water bodies. 
              rwaterpond(ixy)=MIN(MAX(rwaterpond(ixy),wpond_min),wpond_max) ! safety
          !-----------------------------------------------------------------------------------------    
        !=
        !
        end subroutine pond
        !
        !
        !
        subroutine larv_dev(ixy,dt,iounit,ztempwater,zlarvmaturef,rlarv,nlarv,nnumeric)
        ! 
        ! Input from used modules: 
        !
        ! mo_advect.F90 : x
        ! mo_constants.F90 : rlarv_tmin, nlarv_scheme, reps
        ! mo_control.F90 : x (dt, nlarv, nnumeric -> now directly fed to the subroutine)
        ! mo_interface.F90 : x (iounit -> now as input, rlarvmature(4,2) -> now in mo_constants.F90)
        !
        !=
          implicit none
          !
          INTEGER, intent(in) :: ixy   ! Grid point
          REAL, intent(in)    :: dt       ! Time step
          INTEGER, intent(in) :: iounit   !
          INTEGER, intent(in) :: nlarv    ! Resolution of larval development
          INTEGER, intent(in) :: nnumeric ! Advection scheme

          REAL, intent(in) :: ztempwater  ! Temperature of water at given grid point ~ t2m(ixy) + offset
          REAL, intent(inout) :: zlarvmaturef ! Fractional development
          REAL, allocatable, intent(inout) :: rlarv(:,:) ! (0:nlarv,nlon*nlat)

          ! --------------- 10. Larvae maturation - larvae progression ----------------

          IF (ztempwater>rlarv_tmin) THEN
!               IF (ztempwater>rlarv_tmin .AND. ztempwater <rlarv_tmax ) THEN
                 zlarvmaturef=rlarvmature(nlarv_scheme,1)*ztempwater+rlarvmature(nlarv_scheme,2)
                 !zlarvmaturef=zlarvmaturef/(zlarvmaturef*(rlarv_eggtime+rlarv_pupaetime))
                 zlarvmaturef=zlarvmaturef*dt ! timestep 
                 zlarvmaturef=MIN(MAX(0.0,zlarvmaturef),1.0)
          ELSE
             zlarvmaturef=0.0
          ENDIF

          IF (zlarvmaturef>reps) CALL advection(1.0, zlarvmaturef,rlarv(:,ixy),nlarv,nnumeric,iounit)
        end subroutine larv_dev
        !
        !
        !
        subroutine larv_mort(ixy,dt,zsurvp_larv,ztempwater,zmasslarv,zrain, & 
                               rwaterpond,rwaterperm,rwaterurbn,rlarv,rmasslarv,nlarv)
        ! 
        ! Input from used modules: 
        !
        ! mo_advect.F90 : x
        ! mo_constants.F90 : nsurvival_scheme, rlarvsurv, rbiocapacity, wpond_ratio, wperm_ratio, wurbn_ratio
        !                    rlarv_flushmin, rlarv_flushtau
        ! mo_control.F90 : x (dt -> now directly fed to the subroutine)
        ! mo_interface.F90 : x
        !
        !=
          implicit none
          !
          INTEGER, intent(in) :: ixy   ! Grid point
          REAL, intent(in)    :: dt       ! Time step

          INTEGER, intent(in) :: nlarv    ! Resolution of larval development
          REAL, intent(in) :: ztempwater  ! Temperature of water at given grid point ~ t2m(ixy) + offset
          REAL, intent(in) :: zrain       ! Day rainfall at given grid point = rrain(ixy) with safety limits 

          REAL, allocatable, intent(in)    :: rwaterpond(:) !(nlon*nlat) 
          REAL, allocatable, intent(in)    :: rwaterperm(:) !(nlon*nlat)
          REAL, allocatable, intent(in)    :: rwaterurbn(:) !(nlon*nlat)

          REAL, intent(inout) :: zmasslarv ! Total biomass of larvae per m2 of water surface
          REAL, allocatable, intent(inout) :: rmasslarv(:)     ! mass of larvae (0:nlarv)
          REAL, allocatable, intent(inout) :: zsurvp_larv(:) ! (0:nlarv) 
          REAL, allocatable, intent(inout) :: rlarv(:,:)   ! (0:nlarv,nlon*nlat)


          ! Local use only
          INTEGER :: i
          REAL :: zbiolimit, zcapacity, zflushr, zlimit
          ! --------------- 11. Larvae mortality --------------------------------------
          ! 
          ! Larvae mortality is due to
            ! 1) Dessication 
            ! 2) Background due to predation and other causes
            ! 3) Water temperatures
            ! 4) Resource limitation / Overcrowding
            ! 5) Flushing 
            ! 6) Cannibalism (v2.0)
            !=
              ! Initialize the array 
              zsurvp_larv(:)=1.0

              !-----------------------------
              ! 1) Dessication 
              !-----------------------------
              ! - If waterfrac reduces over a timestep, 
              !   the larvae are reduced by the same frac
              !   this of course assumes that the pool are independent
              !
              !-----------------------------
              ! 2) Background due to predation and other causes
              !-----------------------------
              ! - Is integrated into the temperature scheme fit for anopheles gambiae s.s.
              !   with a value of rlarvsurv = 0.987 (see below)
              ! - For aedes albopictus and aedes aegypti is, for now, set to 1.
              !
              !===
                  SELECT CASE(nsurvival_scheme)

                  CASE(1) !Anopheles with martins I
                          ! Do nothing as it's integrated in the fit
                  CASE(2) !Anopheles with martins II
                          ! Do nothing as it's integrated in the fit
                  CASE(3) !Anopheles with Bayoh
                          ! Do nothing as it's integrated in the fit
                  CASE(4) !Aedes albopictus
                    ! Larvae background mortality
                    zsurvp_larv(1:)=rlarvsurv*zsurvp_larv(1:)
                    ! Egg background mortality
                    zsurvp_larv(0)=rlarvsurv*zsurvp_larv(0) ! for now same as larval mortality
                  CASE(5) ! Aedes aegypti
                    ! Larvae background mortality
                    zsurvp_larv(1:)=rlarvsurv*zsurvp_larv(1:)
                    ! Egg background mortality
                    zsurvp_larv(0)=rlarvsurv*zsurvp_larv(0) ! for now same as larval mortality
                  CASE DEFAULT
                        STOP 'invalid survival scheme'
                  END SELECT
              !===
              !
              !-----------------------------
              ! 3) Water temperatures
              !-----------------------------
              !===
                  !------------------ Fit for anopheles gambiae s.s.------------------------------------------------
                  ! Here for function of temperature we use Data from Bayoh and Lindsay 2003,2004
                  !           Mean survival                         Proportion of terminal
                  !            in days (95%         Range of larval  events occurring as    Equality of survival
                  !Temperature
                  !( C)       confidence interval) mortality (days) larval mortality (%)   distributions*
                  !10           2.7 (2.6-2.8)        2-5             100.0                  a
                  !12           3.7 (3.6-3.9)        1-6             100.0                  -
                  !14          20.5 (19.3-21.8)      5-42            100.0                  -
                  !16          25.5 (24.4-26.5)      9-39            100.0   *cycle survival*  b
                  !18          24.9 (23.8-26.2)     10-38             58.0    30.9  0.972      b
                  !20          24.9 (23.6-26.4)      3-31             24.7    23.0  0.987      b
                  !22          18.1 (17.5-18.6)      5-20             24.0    18.3  0.985       -
                  !24          16.4 (15.9-16.8)      6-18             20.7    15.3  0.985    -
                  !26          13.5 (13.2-13.9)      5-15             27.3    13.0  0.976    -
                  !28          11.0 (10.6-11.4)      3-14             33.3    11.4  0.965    c
                  !30          11.2 (10.8-11.5)      4-16             72.7    10.1  0.879    c
                  !32          10.2 (9.9-10.5)       5-13             70.0    9.1   0.876    -
                  !34           8.9 (8.5-9.3)        4-14            100.0                  -
                  !36           6.9 (6.8-7.2)        4-10            100.0                  -
                  !38           4.8 (4.6-4.9)        3-7             100.0                  -
                  !40           2.8 (2.6-2.9)        2-4             100.0                  a
                  ! 
                  ! The *cycle survival* is calculated from the survival and development length
                  ! survival rate as a function of temperature is calculated.
                  ! 
                  ! We fit a scaled logistic curve  smin+(smax-smin)*(1.0-1.0/(1.0+exp((t0-tdata)/tau))) using the NLS package in R: 
                  ! Smax, t0 and tau are fitted.  Smin is a fixed constant at 0.8 
                  ! (you can achieve a good fit with smin at any value between 0 and 0.8, the data does not allow you to specify a first
                  !  guess as it does not cover the high temperature range in a useful way).
                  ! 
                  ! The data is smoothed by a 3 point running mean, with the end points retained:
                  ! 
                  ! R code:
                  ! tdata=c(18,20,22,24,26,28,30,32)
                  ! sdata=c(0.972,0.987,0.985,0.985,0.976,0.965,0.879,0.876)
                  ! sdata=c(0.972,rollmean(sdata,3),0.876)
                  ! fit=nls(sdata ~ smin+(smax-smin)*(1.0-1.0/(1.0+exp((t0-tdata)/tau))) , start=list(t0=t0,tau=tau,smax=smax))
                  !
                  ! smin=0.8 gives:
                  !     Estimate Std. Error t value Pr(>|t|)    
                  ! t0   30.975279   0.310659  99.708 1.92e-09 ***
                  ! tau   2.189333   0.385852   5.674  0.00237 ** 
                  ! smax  0.983665   0.005228 188.164 8.04e-11 ***
                  
                  ! smin=0.7 gives:
                  ! t0   33.1
                  ! tau   2.75
                  ! smax  0.984
                  
                  ! assumed same across all larvae
                  !zsurvp_larv(:)=0.8+(rlarvsurv-0.8)*(1.0-1.0/(1.0+EXP((30.98-ztempwater)/2.18)))
                  !
                  !------------------------------------------------------------------------------------------------------
                  !
                  SELECT CASE(nsurvival_scheme)

                  CASE(1) !Anopheles with martins I
                    zsurvp_larv(:)=zsurvp_larv(:)*(0.7+(rlarvsurv-0.7)*(1.0-1.0/(1.0+EXP((33.1-ztempwater)/2.75))))
                  CASE(2) !Anopheles with martins II
                    zsurvp_larv(:)=zsurvp_larv(:)*(0.7+(rlarvsurv-0.7)*(1.0-1.0/(1.0+EXP((33.1-ztempwater)/2.75))))
                  CASE(3) !Anopheles with Bayoh
                    zsurvp_larv(:)=zsurvp_larv(:)*(0.7+(rlarvsurv-0.7)*(1.0-1.0/(1.0+EXP((33.1-ztempwater)/2.75))))
                  CASE(4) !Aedes albopictus Metelmann [ref]: https://doi.org/10.1098/rsif.2018.0761
                    ! Larvae mortality
                    zsurvp_larv(1:)=zsurvp_larv(1:)*(0.977*EXP(-0.5*((ztempwater-21.8)/16.6)**6))
                    ! Egg mortality
                    zsurvp_larv(0)=zsurvp_larv(0)*(0.955*EXP(-0.5*((ztempwater-18.8)/21.53)**6))
                  CASE(5) !Aedes aegypti Caldwell [ref]: (missing)
                    zsurvp_larv(:)=zsurvp_larv(:)*(-5.99E-3 * (ztempwater-13.56) * (ztempwater-38.29))
                  CASE DEFAULT
                        STOP 'invalid survival scheme'
                  END SELECT
              !===
              ! 
              !-----------------------------
              ! 4) Resource limitation / Overcrowding
              !-----------------------------
              ! - Bomblies slowed development due to overcrowding but 
              !   this causes unrealistically long development
              !   times, and doesn't reflect observations,
              !   so instead we use the overcrowding factor 
              !   to alter the mortality rate for larvae
              !   limitation of resources - negative feedback on numbers
              !   integrate biomass of larvae - bomblies instead slows grow rate 
              !   from v1.3.5 added rwateroccupancy, which gives fractional occupancy by LU type.
              !
              !===
                  zbiolimit=rbiocapacity* &
                  & (rwaterpond(ixy)*wpond_ratio + &  ! temporary ponds (gambiae)
                  &  rwaterperm(ixy)*wperm_ratio + &  ! pools and ponding near streams, rivers and lakes (funestus)
                  &  rwaterurbn(ixy)*wurbn_ratio )    ! water associated with human habitations (cans, tyres etc) Aedes

                  ! The previous parameterization linearly reduces survival rate as a function of food limitation
                  ! 
                  zmasslarv=SUM(rlarv(:,ixy)*rmasslarv(:))
                  zcapacity=MIN(MAX((zbiolimit-zmasslarv)/zbiolimit,0.01),1.0)
                  zsurvp_larv=zsurvp_larv*zcapacity ! Bomblies type capacity limitation

              !===
              !
              !-----------------------------
              ! 5) Flushing
              !----------------------------
              !
              !===
                  zflushr=(1.0-rlarv_flushmin)*EXP(-zrain/rlarv_flushtau)+rlarv_flushmin

                  !
                  ! REPLACE, when we instigate L1-4 larvae will apply
                  DO i=0,nlarv
                     ! greatest flushing to L1 larvae so apply as a linear function
                     zlimit=REAL(i)/REAL(nlarv)
                     ! : is a bug to emulate previous
                     zsurvp_larv(i)=zsurvp_larv(i)*(zlimit*(1.0-zflushr)+zflushr)
                     zsurvp_larv(i)=zsurvp_larv(i)*dt ! timestep
                     zsurvp_larv(i)=MIN(MAX(0.01,zsurvp_larv(i)),1.0)               
                     rlarv(i,ixy)=rlarv(i,ixy)*zsurvp_larv(i)
                  ENDDO
              !===
              !
              !-----------------------------
              ! 6) Cannibalism (v2.0)
              !-----------------------------
              !
              ! - Instead of biolimit in terms of laervae mass, should translate into energy per larvae. 
              ! - Food availability for late stage larvae enhanced by L1/L4 ratio...


        end subroutine larv_mort
        !
        !
        !
        !
        subroutine larv_hatch(ixy,rlarv,rvect,nlarv)
       
        ! 
        ! Input from used modules: 
        !
        ! mo_advect.F90 : x
        ! mo_constants.F90 : x
        ! mo_control.F90 : x 
        ! mo_interface.F90 : x
        !
        !=
          implicit none
          !
          INTEGER, intent(in) :: ixy   ! Grid point
          INTEGER, intent(in) :: nlarv    ! Resolution of larval development
          REAL, allocatable, intent(inout) :: rvect(:,:) ! (0:ninfv,nlon*nlat)
          REAL, allocatable, intent(inout) :: rlarv(:,:) ! (0:nlarv,nlon*nlat)
          ! --------------- 12. Larvae hatching ---------------------------------------

          ! emergence of new females from larvae stage:
          rvect(0,ixy)=rvect(0,ixy)+rlarv(nlarv,ixy)

          ! remove larvae that have now hatched:
          rlarv(nlarv,ixy)=0.0   

        end subroutine larv_hatch

























end MODULE mo_methods