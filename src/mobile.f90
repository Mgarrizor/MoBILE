PROGRAM MOBILE
!
!
! Mobility-Based Integrated Landscape Epidemiology
!
!                       MoBILE
! 
!          Authors: M. Garrido Zornoza & Adrian M. Tompkins
!          Contact: mgarrizoraca@gmail.com & tompkins@ictp.it
!          
!                      (2024)
!
! Developed at The Abdus Salam ICTP, Trieste, Italy 
!
! ========================================
! License: GNU General Public License v3.0
! ========================================
!
! Sources referenced in MoBILE
!
! --------- Cholera --------------------
! [ref:c1] Lorenzo et al. (http://doi.org/10.1098/rsif.2014.0840)
! [ref:c2] Rinaldo et al. (https://doi.org/10.1073/pnas.1203333109)
!


! --------- Malaria --------------------
! [ref:m1] Sama et al. 2006a     (https://doi.org/10.1016/j.trstmh.2005.11.001)
! [ref:m2] Bretscher et al. 2011 (https://doi.org/10.1016/j.epidem.2011.03.002)
! [ref:m3] Nzioki et al. 2023    (https://doi.org/10.1186/s13071-023-05944-5)


! --------- Dengue ---------------------
! [ref:d1]
! [ref:d2]
! [ref:d3]
!
!============================================================================================
! Index                           |- mo_dules                          | Performance (profiler.sh)
!                                 |   /<<subroutine>>                  |        
!                                 |                                    |
! 0) Initialization --------------|------------------------------------|-----------------------------                              
!     0.1 Grid & params           |                                    |
!     0.1.1 Input                 |                                    |
!     0.1.2 No input              |                                    |
!                                 |                                    |
!     0.2 Common information      |                                    |
!                                 |                                    |
!     0.3 Mobility scheme         | [non-functional] --> Dev. with Marie Curie!
!     0.3.1 Empirical network     |                                    |
!     0.3.2 Gravity model         |                                    |
!     0.3.3 Radiation model       |                                    |
!                                 |                                    |
!     0.4 People representation   |                                    |
!     0.4.1 Agents                |                                    |
!     0.4.2 Density               |                                    |
!                                 |                                    |
!     0.5 Disease source          |                                    |
!     0.5.1 Cholera               |                                    |
!     0.5.2 Malaria               |                                    |
!     0.5.3 Dengue [n-func.]      |                                    |
!                                 |                                    |
!     0.6 Spin-up                 |                                    |
!                                 |                                    |
!      **************             |                                    |
!====== Spatial loop =============|====================================|=======================
!      **************             |                                    |
! 1) Integrate source of disease -|------------------------------------|
!                                 |                                    |
!                                 |- mo_source.f90                     |
!    1.1) Bacteria (cholera)      |   /<<source_integrate_B>>          |
!                                 |                                    |
!                                 |- mo_vectri.f90                     |
!    1.2) Vectors (malaria,VECTRI)|   /<<source_integrate_VECTRI>>     |
!                                 |                                    |
! 2) Update health status (bulk) -|------------------------------------|
! --> agents=.false.              |                                    |
!                                 |                                    |
!                                 |- mo_bulk.f90                       |
!    2.1) Cholera                 |   /<<bulk_integrate_SIAR_cholera>> |
!                                 |                                    | 
!                                 |- mo_????.f90                       |
!    2.2) Malaria                 |   /<<bulk_integrate_SEIR_malaria>>  [Non-functional]
!                                 |                                    |
!      ************               |                                    |
!====== Agent loop ===============|====================================|========================
!      ************               |                                    |
! --> agents=.true.               |                                    |
!                                 |                                    |
! 3) Disease ---------------------|------------------------------------|
!                                 |                                    |
!                                 |-mo_agents.f90                      |
!    3.1) Update health status    |   /<<agents_update>>               |
!       - Cholera                 |   //<<agents_cholera>> (SIAR)      |
!       - Malaria                 |   //<<agents_malaria>> (SEIR)      |
!       - Dengue                  |   //<<agents_dengue>>  (SIAR)      |
!                                 |                                    |
!                                 |-mo_agents.f90                      |
!    3.2) Update population age   |   /<<agents_age>>                  |            
!                                 |                                    | 
!                                 |-mo_agents.f90                      |
!    3.3) Calculate bulk stats    |   /<<agents_diagnostics>>          |
!       - Cholera                 |   disID=0 (SIAR)                   |
!       - Malaria                 |   disID=1 (SEIR)                   |
!       - Dengue                  |   disID=2 (????)                   |
!                                 |                                    |
!================================================================================================
!
!-------------------------------------------------------
! Import modules
  USE mo_const
  USE mo_mobility
  USE mo_agents
  USE mo_source
  USE mo_control
  USE mo_netcdf
  USE mo_bulk
  USE mo_grid
  USE mo_namelist
  USE mo_timestep
  USE mo_spinup

! External libraries
  USE mo_ranlib
  !USE, INTRINSIC :: ISO_C_BINDING
  
!----- VECTRI
#ifdef COUPLED
  ! Declarations or interfaces related to the coupled mode
  USE mo_vectri
  !
#endif
!----------------------

  USE omp_lib ! Not in use

implicit none

  !******************************************************************
  ! Loop counters
  integer :: itime     ! Time    (nsteps)
  integer :: ispinup   ! Number of needed spin-up years 
  integer :: oagent

  ! Random number and PDf sampler libraries
  character(len=100) :: phrase
  integer :: seed1, seed2
  integer:: ntest
  integer::nloop
  real, allocatable :: array(:)
  ! CPU time 
  real(kind=8) :: t_start
  real(kind=8) :: t_spin
  real(kind=8) :: t_finish

  ! Wall-clock time
  real(kind=4) :: elapsed_time
  integer      :: start_count, end_count, spin_count, count_rate
  !
  call cpu_time(t_start)
  !t_start = OMP_GET_WTIME()
  CALL SYSTEM_CLOCK(COUNT=start_count, COUNT_RATE=count_rate)
!******************************************************************
!
! Get basic information for the current run
call namelist_inout(run_name,disID,nsteps,seed,spin_up)
!
! ---------------------------------------------------------------------
! Reproducibility: make a run repeatable bit-for-bit when it is re-run
! with the same `seed`, the same number of OpenMP threads, and the same
! schedule. Two things used to stop this from being possible, both fixed
! here:
!   1) RNGLIB (used below, and for the agent-weight sampler gengam) was
!      always seeded from the fixed word 'randomizer', so the namelist
!      `seed` never actually reached it -- every run drew the same
!      RNGLIB numbers regardless of what `seed` was set to. Also, the
!      namelist used to be read further below, i.e. after this seeding
!      already happened, so `seed` could not have been used here even if
!      we had wanted to.
!   2) The intrinsic random number generator (RANDOM_NUMBER, used almost
!      everywhere else: agent health transitions, mobility choices,
!      disease-profile draws) was reseeded from the system clock once at
!      agent start-up and again on every single simulated day -- so two
!      runs of the exact same namelist never produced the same numbers.
! ---------------------------------------------------------------------
!
! Seed RNGLIB from the namelist `seed` (write() turns the integer into a
! phrase, since phrtsd expects a character string to hash into the pair
! of integers (seed1,seed2) that set_initial_seed needs).
write( phrase, '(i0)' ) seed
call initialize( )
call phrtsd( phrase, seed1, seed2 )
call set_initial_seed( seed1, seed2 )
!
! Give every OpenMP thread its own persistent, deterministically-seeded
! random stream (both RNGLIB and the intrinsic generator) -- see
! agents_seed_threads (mo_agents.f90) for why a dedicated one-time
! subroutine is needed instead of a single random_seed() call here.
call agents_seed_threads(seed)
!
! Initialization of the grid and agent worlds
itime = 1
  print '("Pi = ",f6.4)', pi
  !
  ! ************** 0.1 Grid & params **************
  ! If .input.=true then read gridded fields (population density and forcings - rainfall, air temperature, immunity)
  ! and new disease parameters from namelist. Otherwise fall back to idealized world. 
  !
  ! init default constants for disease "disID"
  call const_disease(disID)

  !---- Test gamma-distributed sampling from external libraries ---
  ntest = 100000
  allocate(array(ntest))
  do nloop = 1, ntest
    array(nloop) = gengam(k_NB,k_NB)
  end do
  open(unit=20, file=trim(run_name)//'/gamma_data.txt', status='replace', action='write')
  
  do nloop = 1, ntest
      write(20, '(F12.6)') array(nloop)  ! Writes one value per line
  end do
  
  close(20)
  !-----------------------------------------------------------------
  !
  !
  ! 0.1.1 Input
  if ((input)) then
    ! Namelists
    !=
      !--Human input
      call namelist_human(pop_file,nagent,imm_file)
      !
      !--Climate input
      call namelist_clima(rain_file,t2m_file,area_file)
      !
      !--Init namelist constants, overriding default --> New parameter values from input
      !call namelist_const()
      !
      !--Init grid, pop and forcing fields
      call netcdf_read_grid(pop_file,grid,nlon,nlat,nxy,pop_dens,lon_coord,lat_coord,mask_pop,nsteps)
      !
#ifdef COUPLED
      ! Declarations or interfaces related to the coupled mode
      !=
        call init_constants() ! VECTRI-specific constants
      !=
      !
#endif
      !
      !--Init namelist constants, overriding default --> New parameter values from input
      call namelist_const()

      !e1 = 0.5*e_0  ! e-folding factor in boosted maternal/naive immunity acquisition (fast) [e_0]
      !e2 = 10*e_0   ! e-folding factor in gradual immunity acquisition (slow)                [e_0]
        
      !wperm_default=1.0 ! Dielmo
      !wpond_max=1.0

      ! Fitting round 1
      !wperm_ratio=0.006 ! Dielmo
      !soilinfil_SA=675.16
      !wpond_CN=86.78
      !wpond_ratio=0.48
      !dgono=44.18
      !
      !
#ifdef COUPLED
      !=
        ! Initialize vectri fields (soil, vectors, carrying capacity)
        call init_vectri(pop_dens,mask_pop,nlon,nlat)
      !=
#endif
      !
      print*, gengam(k_NB,k_NB)
      !=
        call grid_allocate(nxy,nlon,nlat,y_coord_1d,x_coord_1d)
      !=
      !
    ! 0.1.2 No input
    elseif ((.not. input)) then !--> Idealized world
      ! Namelists
      !=
        !--Init namelist constants, overwritting default --> New parameter values from input
        call namelist_const()
        !
      !=
      ! init grid and pop
      !=
        nlon =51       ! Number of longitude points
        nlat =51       ! Number of latitude points
        nxy  =nlon*nlat
        call grid_allocate(nxy,nlon,nlat,y_coord_1d,x_coord_1d)
        call grid_no_input(nxy,dx,dy,ncity,seed,H_0,D_pop,pop_dens,D,x_coord_1d,y_coord_1d,radial &
                            ,nlon,nlat,lat_coord,lon_coord,L)
        allocate(mask_pop(nxy))
        mask_pop(:)=.true.
      !=
      !
    else
      print *, 'Check point: Input --> STOP'
      STOP 
    end if !----------------------------------------
    !=
    ! Safety check
    !=
      if ((nsteps > ntime) .and. out_rain) then
        print *, nsteps, ntime
        print *, 'Number of simulation steps exceeds length of forcing --> STOP'
        STOP
      end if
    !=
    ! By now the following should be defined:
    ! - Disease parameters
    ! - Grid parameters : nxy,x_coord_1,y_coord_1d,dx,dy,pop_dens
    ! - Population density and forcing fields
    !
    ! ************** 0.2 Common information **************
! Safety ===============
#ifdef COUPLED   
    coupling =.true.    ! Vector-borne setting
    out_D    =.false.   ! No bulk/densiy model of human movement (might be a to-do in VECTRI)
    out_Q    =.false.   ! No bulk/density model of human movement
    out_B    =.false.   ! No bacterial load
    out_F    =.false.   ! We have not defined a force of infection (might be a to-do)
#else 
    coupling =.false.   ! Cholera setting
    out_t2m  =.false.   ! Temperature is not a forcing field in the cholera model
    out_EIR  =.false.   ! There is no EIR
    out_imm  =.false.   ! There is no immunity dynamics
    out_hbr  =.false.   ! There are no vectors
#endif
!=======!
  !
  ! Initialize distance matrix
  call mob_dist_init(nxy,x_coord_1d,y_coord_1d,lon_coord,lat_coord,dx,dy,input,Re,Pi,mask_pop,dist)
  !
  ! We need to know the lenght of the age structure before creating the NetCDF
  ! output file.
  call agents_read_age(age_weights,age_counts)
  !
  ! Allocate arrays of disease "disID" (SEIAR)
  call grid_dis(disID,nxy,S,E,I,A,A_old,R,EIR,imm,hbr)
  !
  !**********************************
  !
  ! Open NetCDF dataset for output
  if (agents) then
    out_F = .false. ! There is no explicit force of infection with agent method
  end if
  if (.not. rand_seed) then
    out_Q = .false.
  end if
  !
  !
  call netcdf_init(nlon,nlat,nsteps,lon_coord,lat_coord,Var3D)
  !
  ! Save some memory
  deallocate(lon_coord) 
  deallocate(lat_coord)
  !
  ! 0.3 Mobility scheme -------------------------
  !
  ! 0.3.1 Empirical network
  if ((network)) then ! [Non-functional]
    print *, 'Mobility scheme: empirical network'
    print *, 'Check point: mobility scheme -> Empirical network non-functional --> STOP'
    STOP 
  !
  ! 0.3.2 Gravity model
  elseif ((gravity)) then
    print *, 'Mobility scheme: gravity model'
    !
    call mob_gravity_init(nxy,agents,eps,mask_pop,mask_grav,mask_mob,D_grav,pop_dens,dist,Q,Q_2,Q_short,Q_long,m_short,m_long)
    !
  ! 0.3.3 Radiation model
  elseif ((radiation)) then ! [Non-functional]
    print *, 'Mobility scheme: radiation model'
    print *, 'Check point: mobility scheme -> Radiation model non-functional --> STOP'
    STOP
    !
    ! call mob_radiation_init(??) 
    !
  end if !-----------------------------------
  !
  ! Save some memory
  if ((agents) .and. (.not. out_Q)) then
      deallocate(Q)
  end if
  !
  if (.not. out_D) then 
    deallocate(dist)
  end if
  !
  ! 0.4 People representation ------------------- 
  !
  ! 0.4.1 Agents
  print *, '------------------------'
  if ((agents)) then
    print *, "People representation: Agents"
    !
     if (random .and. (.not. rand_seed)) then
        print *, '-- Random initial disease profiles --'
     end if
     call agents_init(nxy,disID,nagent,npeop,nbirths_left,mask_pop,pop_dens,scale,A_cell)
     !
     !
     if (in_imm) then
       !
       call read_slice_imm(itime,imm) ! itime = 1
       !
     end if 
     !
     call agents_pre_diagnostics(disID)
     !
     agent_loop: do oagent=1,nagent
        call agents_diagnostics(disID,oagent)
     end do agent_loop
     !
     call agents_post_diagnostics(disID)
    !
  ! 0.4.2 Density
  elseif ((.not. agents)) then 
    print *, 'People representation: Density (No agents)'
    !
    ! Bulk S(E)I(A)R if no agents 
    call bulk_init(S,I,A,A_old,R,pop_dens,fS_0,fI_0,fA_0,fR_0,nxy,mask_pop,random,rand_seed)
    !
  end if !-----------------------------------
  !
  ! 0.5 Disease source 
  !
  ! 0.5.1 Cholera
  if ((.not. coupling)) then
    !
    A_old = A
    call source_init(Q,B_0,beta,m,nxy,agents,seed,random,rand_seed,exc,out_rain,exc_clim,B,B_old,F,radial,pop_dens,mask_pop,xy_seed)
    !
    if (random .and. rand_seed) then
        print '("Number of neighbours connected to source: ",i6," ")', sum(merge(1,0,(mask_grav(xy_seed,:))))
    end if
    !     
  ! 0.5.2 Malaria
  else
    ! Do nothing as source of disease (vector density) has been initialized in the above call to init_vectri
  end if
  !
  if (agents) then
    deallocate(mask_grav)
    deallocate(Q_short)
    deallocate(Q_long)
  end if
  !
!=
! CPU stats
call cpu_time(t_finish)
print *, '-- Initialisation took --'
print '("CPU:       ",f6.3," seconds")',(t_finish-t_start)

! OMP Wall-clock stats
!t_finish = OMP_GET_WTIME()

! Wall-clock stats
CALL SYSTEM_CLOCK(COUNT=end_count)
elapsed_time = REAL(end_count - start_count) / REAL(count_rate)
print '("Wall time: ",f6.3," seconds")',elapsed_time
print *, '------------------------'
! 
print *, wperm_default
!********************************************************
! 0.6 Spin-up
!=
if (spin_up==1) then
  !
  SU_conv=.false.
  SU_tol=0.015

  allocate(SU_old(nxy))
  allocate(SU_new(nxy))
  SU_old(:) = 0.
  SU_new(:) = 0.
  ispinup = 0
  !
  print '("Starting Spin-up")'

  ! Redirect t2m/rainfall to a capped multi-year climatology so the
  ! convergence loop below integrates against a typical seasonal cycle
  ! instead of replaying the raw first year; time_step is untouched.
  call build_spinup_climatology()

  do while (.not. SU_conv)
    !
    SU_old(:) = SU_new(:)
    SU_new(:) = 0.
    !
    spin_up_loop: do itime=1,365
    !
    call time_step(disID,itime)
    !
    SELECT case(disID)
    case (0) ! Cholera

    case (1) ! Malaria
      !
      SU_new(:) = SU_new(:) + imm(:)
      !SU_new(:) = imm(:)
      !
    case default
      print *, "Incorrect case, choose disID between: 0 (cholera) and 1 (malaria)"
    STOP
    end SELECT
    !
    end do spin_up_loop
    !
    SU_new(:) = SU_new(:)/365
    !
    ! Convergence to equilibrium by Direct Integration (SI) --> To Do: Implement Anderson Acceleration (AA) and select method from flag
    call DI(SU_new,SU_old,SU_tol,SU_conv)
    ispinup = ispinup + 1
    !
  end do
  !
  ! Swap t2m/rainfall back to the real driver record for the main loop.
  call restore_spinup_forcing()
  !
  deallocate(SU_new)
  deallocate(SU_old)
  !
  ! CPU stats
  call cpu_time(t_spin)
  write(*,*) ' '
  print *, '-- Spin-up took --'
  print '("CPU:      ",f6.3," minutes")',(t_spin-t_finish)/60.
  
  ! OMP Wall-clock stats
  !t_finish = OMP_GET_WTIME()
  
  ! Wall-clock stats
  CALL SYSTEM_CLOCK(COUNT=spin_count)
  elapsed_time = REAL(spin_count - end_count) / REAL(count_rate)
  print '("Wall time:",f6.3," minutes")',elapsed_time/60.
  print *, 'Number of spin-up years: ', ispinup
  print *, '------------------------'
!=
end if 
!
!=
!
! Write initial conditions (after spin-up)
call netcdf_3D_output(1,Var3D) ! itime = 1
! 
print '("Integrate: ",i6," days.")', nsteps
print *, '------------------------'
!
!********************************************************
! Time integration
time_loop: do itime=2,nsteps
  !
  call time_step(disID,itime)
  !
  WRITE(*,'(1a1,A11,I6,A2,I6,A2,F6.1,A2)', advance='no') char(13),'Integrating',itime,' /',nsteps,' -',(real(itime)/(nsteps)*100.),' %'
  !
  ! Write 3D fields (x,y,t) here
  call netcdf_3D_output(itime,Var3D)
  !
end do time_loop
!********************************************************
!
! Write 2D fields (x,y) here and close NetCDF file
call netcdf_2D_output()
!
!t_finish = OMP_GET_WTIME()
!
! CPU stats
call cpu_time(t_finish)
write(*,*) ' '
print *, '-- Program finished successfully after --'
print '("CPU:      ",f6.3," minutes")',(t_finish-t_start)/60.

! OMP Wall-clock stats
!t_finish = OMP_GET_WTIME()

! Wall-clock stats
CALL SYSTEM_CLOCK(COUNT=end_count)
elapsed_time = REAL(end_count - start_count) / REAL(count_rate)
print '("Wall time:",f6.3," minutes")',elapsed_time/60.
print *, '------------------------'
write(*,*) ' '
!
end PROGRAM MOBILE

