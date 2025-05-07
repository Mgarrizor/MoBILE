PROGRAM MOBILE
!
!
! --------- ICTP's agent-based (AB) model --------
!
! Mobility-Based Integrated Landscape Epidemiology
!
!                       MoBILE
!
!                      (model) by
!
!          Adrian M. Tompkins (tompkins@ictp.it) 
!          Miguel G. Zornoza  (mgarrizoraca@gmail.com)
!          
!                      (2024)
!
! License: GNU General Public License v3.0
!
!
! Referenced sources in MoBILE
!
! [1] Lorenzo et al. (http://doi.org/10.1098/rsif.2014.0840)
! [2] Rinaldo et al. (https://doi.org/10.1073/pnas.1203333109)
!
!
!
!********************************************************************
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

  USE omp_lib ! Not in use


  implicit none

!************************************************
!=====================================================================
! Index                           |- mo_dules                        #        
!                                 |   /subroutines                   #        
!                                 |                                  #
! 0) Initialization --------------|                                  #
!     0.1 Grid & params           |
!     0.1.1 Input                 |
!     0.1.2 No input              |
!                                 |
!     0.2 Common information      |   
!                                 |           
!     0.3 Mobility scheme         |   
!     0.3.1 Empirical network     |
!     0.3.2 Gravity model         |
!     0.3.3 Radiation model       | 
!                                 |                     
!     0.4 People representation   |
!     0.4.1 Agents                |
!     0.4.2 Density               |
!                                 |
!     0.5 Disease source          |
!     0.5.1 Cholera               |   
!     0.5.2 Malaria               |                                  #
!                                 |                                  #
! 1) Replenishment ---------------|- mo_growth.f90 ------------------#
!       - Population growth       |                                  #
! 2) Human mobility --------------|- mo_migration.f90                #
! 3) Disease ---------------------|- mo_disease.f90                  #
!       - Cholera                 |                                  #
!       - Malaria (non-func.)     |                                  #
! 4) Source of disease -----------|- mo_source.f90                   #
!       - Bacteria                |                                  #
!        - Vector (non-func.)     |                                  #
!                                 |                                  #
!=====================================================================

  !******************************************************************
  ! Loop counters
  integer :: itime     ! Time    (nsteps)
  integer :: iagent    ! Agents  (nagents)
  integer :: ixy       ! Space   (nxy = nx*ny = nlon*nlat)
  real :: conv1, conv2
  ! Get time 
  real :: t_start
  real :: t_finish
  call cpu_time(t_start)

  !******************************************************************
  !
  ! Get basic information for the current run
  call namelist_inout(run_name,disID,nsteps,seed,spin_up)
  !
  print '("Spin up: ",i6," days.")', spin_up
  !
  print '("Integrate: ",i6," days.")', nsteps
  !
  time_loop: do itime=1,nsteps+spin_up
  !=
    !=
      if((itime==1)) then
        print '("Pi = ",f6.4)', pi
      !=
        ! ************** 0.1 Grid & params **************
        ! If .input.=true then read gridded fields (population density and forcings - rainfall, air temperature)
        ! and new disease parameters from namelist. Otherwise fall back to idealized world 
        !
        ! init default constants for disease "disID"
        call const_disease(disID)
        !
        !
        ! 0.1.1 Input
        if ((input)) then
          ! Namelists
          !=
            !--Human input
            call namelist_human(pop_file,nagent)
            !
            !--Climate input
            call namelist_clima(rain_file,t2m_file)
            !
            !--Init namelist constants, overriding default --> New parameter values from input
            call namelist_const()
            !
            !--Init grid, pop and forcing fields
            call netcdf_read_grid(pop_file,grid,nlon,nlat,nxy,pop_dens,lon_coord,lat_coord,mask_pop)
          !=
          ! Safety check
          !=
            if ((nsteps >= ntime) .and. out_rain) then
              print *, 'Number of simulation steps exceeds length of forcing --> STOP'
              STOP
            end if
          !=
          ! 
          !=
            call grid_allocate(nxy,nlon,nlat,y_coord_1d,x_coord_1d)
          !=
          !
        ! 0.1.2 No input
        elseif ((.not. input)) then !--> Idealized world
          ! Namelists
          !=
            !--Init namelist constants, overriding default --> New parameter values from input
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
        ! By now the following should be defined:
        ! - Disease parameters
        ! - Grid parameters : nxy,x_coord_1,y_coord_1d,dx,dy,pop_dens
        ! - Population density and forcing fields
        !
        ! ************** 0.2 Common information **************
        !
        ! Initialize distance matrix
        call mob_dist_init(nxy,x_coord_1d,y_coord_1d,lon_coord,lat_coord,dx,dy,input,Re,Pi,mask_pop,dist)
        !
        ! Allocate arrays of disease "disID"
        call grid_dis(disID,nxy,S,E,I,A,A_old,R)
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
        call netcdf_init(nlon,nlat,nsteps+1,lon_coord,lat_coord,Var3D)
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
        !
        ! 0.3.2 Gravity model
        elseif ((gravity)) then
          print *, 'Mobility scheme: gravity model'
          !
          call mob_gravity_init(nxy,agents,eps,mask_pop,mask_grav,mask_mob,D_grav,pop_dens,dist,Q,Q_cum)
          !
        ! 0.3.3 Radiation model
        elseif ((radiation)) then ! [Non-functional]
          print *, 'Mobility scheme: radiation model'
          !
          ! call init_radiation  
          !
        end if !-----------------------------------
        !
        ! Save some memory
        if ((agents) .and. (.not. out_Q)) then
            deallocate(Q) ! Safe some memory
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
        if ((agents)) then ![Non-functional]
          print '("People representation: Agents", I8)', nagent
          !'("Pi = ",f4.2)', pi
           call agents_init(nxy,disID,nagent,npeop,nattempt,mask_pop,pop_dens,scale,dist)
           call agents_diagnostics(disID,scale,nalive)
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
        else ![Non-functional]
          !
        end if
        !
        if (agents) then
          deallocate(mask_grav)
          deallocate(Q_cum)
        end if
        !
      call cpu_time(t_finish)
      print '("Getting ready took = ",f6.3," minutes.")',(t_finish-t_start)/60.
      print *, '------------------------'
      !
      !=  
      endif ! End If time==1 *******************
      !
      !
      if(itime==(spin_up+1)) then
        ! Write initial conditions 
        call netcdf_3D_output(itime-spin_up,Var3D)
        !
        write(*,*) ' '
        !
      end if  
      !
      ! 4) Integrate source of disease --> dt_B/dt, dt_V/dt, ...
      ! 5) Update health status --> .agents.=false
      spatial_loop: do ixy=1,nxy 
        if (mask_pop(ixy)) then
          ! 
          ! No need for an accurate integration scheme,
          ! since greater sources of uncertainty are present.
          ! Explicit Euler dB_new = dB_old + f(B(t),...)*dt
          !=
            !
            SELECT case(disID)
            case (0) ! Cholera
            ! 4.1) Source
            !
            ! B(t) --> B(t + dt)
              call source_integrate_B(ixy,itime,nxy,agents,exc,out_rain,exc_clim,rainfall,I,D,Q,mask_grav,B_old,A_old,dt,mu_b,theta_e,theta_p,beta,m,eps,B,F)
            !
            ! 5.1) Health
              if (.not. agents) then 
                ! Densities S(t) --> S(t + dt), ...
                call bulk_integrate_SIAR_cholera(ixy,S,I,A,R,pop_dens,F,dt,mu,rho,sigma,gamma,alpha,eps)
                !
              end if
              !
            case (1) ! Malaria [Non-functional]
            ! 
            ! 4.2) Source
            !
            ! V(t, ixy, sporo_old) --> V(t + dt, ixy, sporo_new)
            ! call source_integrate_VECTRI(x_coord_1d(ixy), y_coord_1d(ixy), nbites, V) --> Do we need the S,E,I,R bulk stats?
            ! **Input**
            !   - ixy       - grid point
            !   - SEIR(:)   - bulk stats?
            !   - nbites(:) - number/density of infective bites (human to vector). 
            !                 This (nbites calculation) is handled in the agent methods and thus benefits from agent attributes.
            !                 We then feed it to VECTRI to inform the sporogonic cycle routine.
            ! **Output**
            !   - Updated vector density and sporogony state, V(t + dt, ixy, sporo)
            !
            ! 5.2) Health 
              if (.not. agents) then 
                ! Densities S(t) --> S(t + dt), ...
                !call bulk_integrate_SEIR_Malaria(ixy,V,...) --> this is the way malaria is currently treated in VECTRI
              end if
              !
            case default
              print *, "Incorrect case, choose disID between: 0 (cholera) and 1 (malaria)"
            STOP
            end SELECT
            !
          !=
        end if ! End mask_pop(ixy)
      end do spatial_loop
      !
      ! 6) Update health status --> Agents
      if ((agents)) then
        ! Reset base excretion array
        exc(:) = 0.
        !
        ! Reset rainfall-driven excretion array
        if (out_rain) then
          exc_clim(:) = 0.
        end if
        !
        ! Reset growth array
        nattempt(:) = 0.
        !
        call random_seed()
        agent_loop: do iagent=1,nagent   
        !
          call agents_update(disID,iagent,itime,nattempt(:))

          if (MOD(itime,365)==0) then ! Ignore calendar type
            !
            call agents_age(iagent)
            !
          end if
        !
        end do agent_loop
        ! Scale excretion events to density
        exc(:) = scale*exc(:)
        !
        if (out_rain) then
          exc_clim(:) = scale*exc_clim(:)
        end if
        !
        call agents_diagnostics(disID,scale,nalive)  ! Compute bulk stats
        !
      end if
      !
      B_old = B
      A_old = A
      !
      ! Check for demographic convergence
      conv1 = 0.
      conv2 = 0.
      do ixy = 1,nxy
        if (mask_pop(ixy)) then
            !
            conv1 = conv1 + (scale*npeop(ixy) - alpha/mu * I(ixy))
            conv2 = conv2 + (1+ gamma/(rho+mu))*(I(ixy)+ A(ixy)) + S(ixy)  
            !
        end if
      end do
      !
      ! Write 3D fields (x,y,t) here
      if (itime > spin_up) then
        !
        if (agents) then
            WRITE(*,'(1a1,A11,F6.1,A2, A16, F6.2, A2, A4, F6.2, A4, F6.2)', advance='no') char(13),'Integrating',(real(itime-spin_up)/(nsteps)*100.),' %', &
                                                                 ' // Agents alive', real(nalive)/real(nagent)*100, '%', ' =? ', &
                                                                 conv1/scale/nagent*100, ' =? ', conv2/scale/nagent*100
                                                                  
        else
            WRITE(*,'(1a1,A11,F6.1,A2)', advance='no') char(13),'Integrating',(real(itime-spin_up)/(nsteps)*100.),' %'

        end if 
        call netcdf_3D_output(itime+1-spin_up,Var3D)
        
      else
        !
        if (agents) then
            WRITE(*,'(1a1,A7,F6.1,A2, A16, F6.2, A2, A4, F6.2, A4, F6.2)', advance='no') char(13),'Spin Up',(real(itime)/(spin_up)*100.),' %', &
                                                                 ' // Agents alive', real(nalive)/real(nagent)*100, '%', ' =? ', &
                                                                 conv1/scale/nagent*100, ' =? ', conv2/scale/nagent*100
                                                                 
        else
            WRITE(*,'(1a1,A7,F6.1,A2)', advance='no') char(13),'Spin Up',(real(itime)/(spin_up)*100.),' %'
        !
        end if
      end if
      !
  !===
  !
  end do time_loop
  !
  !
  !
  WRITE(*,*) ' '
  !
  ! Write 2D fields (x,y) here and close NetCDF file
  call netcdf_2D_output()
  !
  call cpu_time(t_finish)
  print '("Program finished successfully after = ",f6.3," minutes.")',(t_finish-t_start)/60.
  !
end PROGRAM MOBILE

