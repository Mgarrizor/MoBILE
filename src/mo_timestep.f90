MODULE mo_timestep
! This module contains one time step of the model, this is
! one spatial and one agent loop.

! Author: Miguel Garrido Zornoza (2025)
! Contact: mgarrizoraca@gmail.com

!-------------------------------------------------------
! Import modules
  USE mo_const
! USE mo_mobility
  USE mo_agents
  USE mo_source
  USE mo_control
  USE mo_netcdf
  USE mo_bulk
! USE mo_grid
! USE mo_namelist

  !USE, INTRINSIC :: ISO_C_BINDING
  USE omp_lib
!----- VECTRI
#ifdef COUPLED
  ! Declarations or interfaces related to the coupled mode
  USE mo_vectri
  !
#endif
!----------------------

implicit none

CONTAINS 


subroutine time_step(disID,itime)
    
    implicit none

    integer, intent(in) :: disID
    integer, intent(in) :: itime

    ! Local use only

    integer :: ixy       ! Looping spatial index
    integer :: iagent    ! Looping agent index

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
            case (1) ! Malaria
            ! 
            ! 1.2) Source
            !
            ! V(t, ixy, sporo_old) --> V(t + dt, ixy, sporo_new)
            !
! Declarations or interfaces related to the coupled mode
#ifdef COUPLED
            !
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
               !
               !   1) nbites(:)/npeop(:) - "Success" fraction of infective bites (human to vector). 
               !                  The nbites(:) calculation is handled in the agent methods and thus benefits from agent attributes.
               !                  We then feed it to VECTRI to inform the sporogonic cycle routine.
               !
               ! **Output from VECTRI**
               !
               !   Updated vector and larval densities as well as sporogonic state, V(t + dt, ixy, sporo_new):
               !
               !   1) rvect(ixy)  - vector density array 
               !   2) rgonof(ixy) - gonotrophic factor for proportion of susceptible and infective vectors searching for a blood meal
               !
            !==
            ! 2.2) Update health status (bulk)
              if (.not. agents) then ! [Non-functional]
                ! Densities S(t) --> S(t + dt), ...
                !call bulk_integrate_SEIR_malaria(ixy,V,...) --> this is the way malaria is currently handled in VECTRI
                print*, "Bulk (VECTRI) malaria subroutine is non-functional yet --> Stop"
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
      !=
        !
        ! Note: this used to call random_seed() here, with no arguments, at the start
        ! of every single simulated day. That draws a fresh seed from the system clock
        ! each time, which broke reproducibility twice over: it discarded the
        ! deterministic sequence the run started with, and it only ever reset the
        ! calling (master) thread's numbers anyway, doing nothing for the other
        ! threads below. The random number generator is now seeded once, for every
        ! thread, at program start (see agents_seed_threads in mo_agents.f90) and
        ! never touched again -- do not add a reseed call back here.
        !
        ! Pre-diagnostics calculations
        call agents_pre_diagnostics(disID)
        !
        ! SCHEDULE(STATIC) is made explicit (rather than left as the unstated
        ! compiler default) because reproducibility depends on it: which thread
        ! processes a given agent determines which random number stream that
        ! agent's decisions are drawn from (see agents_seed_threads). STATIC is the
        ! only schedule kind whose thread-to-agent assignment is a fixed function of
        ! (nagent, number of threads) alone -- DYNAMIC/GUIDED depend on runtime
        ! timing and would silently break reproducibility even with everything else
        ! in place.
!$OMP PARALLEL DO SCHEDULE(STATIC)
        agent_loop: do iagent=1,nagent
        !
        ! 3.1) Update health status
        !=
          ! Update health status
          call agents_update(disID,iagent,itime,nattempt,npeop,nbites,m_0,m_1,m_all)
          !
          ! Gather diagnostics of iagent
          call agents_diagnostics(disID,iagent)
        !=
        !
        end do agent_loop
!$OMP END PARALLEL DO
        !
        !
        if (in_imm) then
          !
          call read_slice_imm(itime,imm)
          !
        end if 
        !
        ! Post-diagnostics calculations
        call agents_post_diagnostics(disID)
        !
      !=
      end if ! End agent methods -------------------------------------------------
      !
!===
!
end subroutine time_step



end MODULE mo_timestep