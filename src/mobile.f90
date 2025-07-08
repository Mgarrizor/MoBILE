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
!          M. Garrido Zornoza  (mgarrizoraca@gmail.com)
!          
!                      (2024)
!
! License: GNU General Public License v3.0
!
!
! Referenced sources in MoBILE
!
! --------- Cholera --------------------
! [ref:c1] Lorenzo et al. (http://doi.org/10.1098/rsif.2014.0840)
! [ref:c2] Rinaldo et al. (https://doi.org/10.1073/pnas.1203333109)
!


! --------- Malaria --------------------
! [ref:m1] Sama et al. 2006a (https://doi.org/10.1016/j.trstmh.2005.11.001)
! [ref:m2] Bretscher et al. 2011 (https://doi.org/10.1016/j.epidem.2011.03.002)
! [ref:m3] Nzioki et al. 2023 (https://doi.org/10.1186/s13071-023-05944-5)


! --------- Dengue ---------------------
! [d1]
! [d2]
! [d3]
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

  !USE, INTRINSIC :: ISO_C_BINDING
  
!----- VECTRI
#ifdef COUPLED
  ! Declarations or interfaces related to the coupled mode
  USE mo_vectri
  !
#endif
!----------------------

!  USE omp_lib ! Not in use

  implicit none

!************************************************
!=======================================================================
! Index                           |- mo_dules                          #        
!                                 |   /<<subroutine>>                  #        
!                                 |                                    #
! 0) Initialization --------------|------------------------------------#                                   
!     0.1 Grid & params           |                                    #
!     0.1.1 Input                 |                                    #
!     0.1.2 No input              |                                    #
!                                 |                                    #
!     0.2 Common information      |                                    #
!                                 |                                    #
!     0.3 Mobility scheme         |                                    #
!     0.3.1 Empirical network     |                                    #
!     0.3.2 Gravity model         |                                    #
!     0.3.3 Radiation model       |                                    #
!                                 |                                    #
!     0.4 People representation   |                                    #
!     0.4.1 Agents                |                                    #
!     0.4.2 Density               |                                    #
!                                 |                                    #
!     0.5 Disease source          |                                    #
!     0.5.1 Cholera               |                                    #
!     0.5.2 Malaria               |                                    #
!                                 |                                    #
!====== Spatial loop =============|====================================#
! 1) Integrate source of disease -|------------------------------------#
!                                 |                                    #
!                                 |- mo_source.f90                     #
!    1.1) Bacteria (cholera)      |   /<<source_integrate_B>>          #
!                                 |                                    #
!                                 |- mo_vectri.f90                     #
!    1.2) Vectors (malaria,VECTRI)|   /<<source_integrate_VECTRI>>     #
!                                 |                                    #
! 2) Update health status (bulk) -|------------------------------------#
! --> agents=.false.              |                                    #
!                                 |                                    #
!                                 |- mo_bulk.f90                       #
!    2.1) Cholera                 |   /<<bulk_integrate_SIAR_cholera>> #
!                                 |                                    # 
!                                 |- mo_????.f90                       #
!    2.2) Malaria                 |   /<<bulk_integrate_SEIR_Malaria>>  [Non-functional]
!                                 |                                    #
!====== Agent loop ===============|====================================#
! --> agents=.true.               |                                    #
!                                 |                                    #
! 3) Disease ---------------------|------------------------------------#
!                                 |                                    #
!                                 |-mo_agents.f90                      #
!    3.1) Update health status    |   /<<agents_update>>               #
!       - Cholera                 |   disID=0 (SIAR)                   #
!       - Malaria (non-func.)     |   disID=1 (SEIR)                   #
!                                 |                                    #
!                                 |-mo_agents.f90                      #
!    3.2) Update population age   |   /<<agents_age>>                  #            
!                                 |                                    # 
!                                 |-mo_agents.f90                      #
!    3.3) Calculate bulk stats    |   /<<agents_diagnostics>>          #
!       - Cholera                 |   disID=0 (SIAR)                   #
!       - Malaria                 |   disID=1 (SEIR)                   #
!                                 |                                    #
!=======================================================================

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
            call namelist_clima(rain_file,t2m_file,area_file)
            !
            !--Init namelist constants, overriding default --> New parameter values from input
            call namelist_const()
            !
            !--Init grid, pop and forcing fields
            call netcdf_read_grid(pop_file,grid,nlon,nlat,nxy,pop_dens,lon_coord,lat_coord,mask_pop)

#ifdef COUPLED
            ! Declarations or interfaces related to the coupled mode
            !=
              call init_constants() ! VECTRI-specific constants
              wurbn_ratio = 1e-6    ! 
              call init_vectri(pop_dens,mask_pop,nlon,nlat)

            !=
            !
#endif
            
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
        ! By now the following should be defined:
        ! - Disease parameters
        ! - Grid parameters : nxy,x_coord_1,y_coord_1d,dx,dy,pop_dens
        ! - Population density and forcing fields
        !
        ! ************** 0.2 Common information **************
! Safety ===============
#ifdef COUPLED     
        out_D    =.false.
        out_Q    =.false.
        out_B    =.false.
        out_F    =.false.
        out_A    =.true.
        out_E    =.true.
        coupling =.true.
#else 
        coupling =.false.
        out_t2m  =.false.
        out_EIR  =.false.
#endif
!=======!
        !
        ! Initialize distance matrix
        call mob_dist_init(nxy,x_coord_1d,y_coord_1d,lon_coord,lat_coord,dx,dy,input,Re,Pi,mask_pop,dist)
        !
        ! Allocate arrays of disease "disID" (SEIAR)
        call grid_dis(disID,nxy,S,E,I,A,A_old,R,EIR)
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
          call mob_gravity_init(nxy,agents,eps,mask_pop,mask_grav,mask_mob,D_grav,pop_dens,dist,Q,Q_2,Q_short,Q_long,m_short,m_long)
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
          print *, "People representation: Agents"
          !'("Pi = ",f4.2)', pi
           call agents_init(nxy,disID,nagent,npeop,nattempt,mask_pop,pop_dens,scale,dist,A_cell)
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
          ! Do nothing as source of disease (vector density) has been initialized in the above call to init_vectri
        end if
        !
        if (agents) then
          deallocate(mask_grav)
          deallocate(Q_short)
          deallocate(Q_long)
        end if
        !
      call cpu_time(t_finish)
      print '("Getting ready took = ",f6.3," minutes.")',(t_finish-t_start)/60.
      print *, '------------------------'
      !
      !=  
      endif ! End If time==1 *******************
      
      !
      if(itime==(spin_up+1)) then
        ! Write initial conditions 
        call netcdf_3D_output(itime-spin_up,Var3D)
        !
        write(*,*) ' '
        !
      end if  
      !
      ! 1) Integrate source of disease --> dt_B/dt, dt_V/dt, ...  ==================================================================================
      ! 2) Update health status --> .agents.=false
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
            ! 1.1) Source
            !
            ! B(t) --> B(t + dt)
              call source_integrate_B(ixy,itime,nxy,agents,exc,out_rain,exc_clim,rainfall,I,D,Q,mask_grav,B_old,A_old,dt,mu_b,theta_e,theta_p,beta,m,eps,B,F)
            !
            ! 2.1) Update health status (bulk)
              if (.not. agents) then 
                ! Densities S(t) --> S(t + dt), ...
                call bulk_integrate_SIAR_cholera(ixy,S,I,A,R,pop_dens,F,dt,mu,rho,sigma,gamma,alpha,eps)
                !
              end if
              !
            case (1) ! Malaria [Non-functional]
            ! 
            ! 1.2) Source
            !
            ! V(t, ixy, sporo_old) --> V(t + dt, ixy, sporo_new)
            !
! Declarations or interfaces related to the coupled mode
#ifdef COUPLED
          
            ! Update point meteo drivers
            !
             point_rain = rainfall(ixy,itime)
             point_temp = t2m(ixy,itime)
            !
            !==
               ! Take a VECTRI time step
               call source_integrate_VECTRI(ixy,nbites,npeop,rvect,rlarv,point_rain,point_temp,pop_dens,mask_pop, &
                                          dt,zvecinfc,zvect_density,zvect_one_d_density,zgonof)
               !                            
               rgonof(ixy) = zgonof
               ! **Input from agent methods**
     
               !   1) nbites(:) - "Success" fraction of infective bites (human to vector). 
               !                  This (nbites calculation) is handled in the agent methods and thus benefits from agent attributes.
               !                  We then feed it to VECTRI to inform the sporogonic cycle routine.
               
               ! **Output from VECTRI**

               !   Updated vector and larval densities as well as sporogony state, V(t + dt, ixy, sporo_new):
               !
               !   1) rvect(ixy)  - vector density array 
               !   2) rgonof(ixy) - gonotrophic factor for proportion of susceptible and infective vectors searching for a blood meal
               !
            !==
            ! 2.2) Update health status (bulk)
              if (.not. agents) then ! [Non-functional]
                ! Densities S(t) --> S(t + dt), ...
                !call bulk_integrate_SEIR_Malaria(ixy,V,...) --> this is the way malaria is currently handled in VECTRI
                print*, "Bulk malaria subroputine is non-functional yet --> Stop"
                STOP
              end if
              !
#endif  
            case default
              print *, "Incorrect case, choose disID between: 0 (cholera) and 1 (malaria)"
            STOP
            end SELECT
            !
          !=
        end if ! End mask_pop(ixy)
      end do spatial_loop
      !
      ! 3) Disease --> Agents ==================================================================================
      if ((agents)) then


        if (disID == 0) then  
          ! Reset base excretion array
          exc(:) = 0.
          !
          ! Reset rainfall-driven excretion array
          if (out_rain) then
            exc_clim(:) = 0.
          end if
          !
        end if
        ! Reset growth array
        nattempt(:) = 0.
        !
        if (disID == 1) then  
          ! Reset number of infective bites
          nbites(:) = 0
          !b_rate
          m_0(:) = b_rate*rgonof(:)*rvect(0,:)/(npeop(:)+K_h)*scaleI*P_a
          m_1(:) = b_rate*rgonof(:)*rvect(ninfv,:)/(npeop(:)+K_h)*scaleI*P_a
          !
        end if
        call random_seed()
        !
        agent_loop: do iagent=1,nagent   
        !
        ! 3.1) Update health status
          !
          call agents_update(disID,iagent,itime,nattempt,npeop,nbites,m_0,m_1)

          if (MOD(itime,365)==0) then ! Ignore calendar type
            !
            ! 3.2) Update population age
            call agents_age(iagent)
            !
          end if
        !
        end do agent_loop

        if (disID == 0) then
          ! Scale excretion events to density
          exc(:) = scale(:)*exc(:)
          !
          if (out_rain) then
            exc_clim(:) = scale(:)*exc_clim(:)
          end if
          !
        end if
        !
        ! 3.3) Calculate bulk SEIAR
        call agents_diagnostics(disID,scale,nalive)  ! Compute bulk stats
        !
        ! Post-diagnostics calculations
        !
        if (disID == 1) then  
          ! Calculate average daily EIR
          where(mask_pop(:)) EIR(:) = EIR(:)/npeop(:)/P_a
          !
        end if
      end if ! End agent methods -------------------------------------------------
      !
      if (disID == 0) then
        !
        B_old = B
        A_old = A
        !
        ! Check for demographic convergence (cholera model)
        conv1 = 0.
        conv2 = 0.
        do ixy = 1,nxy
          if (mask_pop(ixy)) then
              !
              conv1 = conv1 + (scale(ixy)*npeop(ixy) - alpha/mu * I(ixy))
              conv2 = conv2 + (1+ gamma/(rho+mu))*(I(ixy)+ A(ixy)) + S(ixy)  
              !
          end if
        end do
        !
      end if
      !
      if (itime > spin_up) then
      !=
        !
        WRITE(*,'(1a1,A11,F6.1,A2)', advance='no') char(13),'Integrating',(real(itime-spin_up)/(nsteps)*100.),' %'
        !
        ! Write 3D fields (x,y,t) here
        call netcdf_3D_output(itime+1-spin_up,Var3D)
        !
      !=
      else
        !
        WRITE(*,'(1a1,A7,F6.1,A2)', advance='no') char(13),'Spin Up',(real(itime)/(spin_up)*100.),' %'
        !
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

