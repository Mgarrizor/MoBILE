MODULE mo_timestep
! This module contains one time step of the model, this is
! the spatial and agent loops.

! Miguel Garrido Zornoza 2025
! mgarrizoraca@gmail.com

!-------------------------------------------------------
! Import modules
  USE mo_const
! USE mo_mobility
  USE mo_agents
  USE mo_source
  USE mo_control
!  USE mo_netcdf
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
    real :: conv1, conv2

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
               !   Updated vector and larval densities as well as sporogony state, V(t + dt, ixy, sporo_new):
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
        !
        ! Reset growth array
        nattempt(:) = 0.
        !
        SELECT case(disID)
        case (0) ! Cholera
          !
          ! Reset base excretion array
          exc(:) = 0.
          !
          ! Reset rainfall-driven excretion array
          if (out_rain) then
            exc_clim(:) = 0.
          end if
          !
        case (1) ! Malaria
          !
          ! Reset number of infective bites
          nbites(:) = 0
          !
          ! Compute base interaction rates
          !
          ! Human to vector
          m_0(:) = b_rate*rgonof(:)*rvect(0,:)/(npeop(:)+K_h)*scaleI!*P_a
          ! Vector to human
          m_1(:) = b_rate*rgonof(:)*rvect(ninfv,:)/(npeop(:)+K_h)*scaleI!*P_a
          !
        case default
          print *, "Incorrect case, choose disID between: 0 (cholera) and 1 (malaria)"
        STOP
        end SELECT
        !
        ! "Re-initialise" random number generator
        call random_seed()
        !
!$OMP PARALLEL DO
        agent_loop: do iagent=1,nagent   
        !
        ! 3.1) Update health status
          !
          call agents_update(disID,iagent,itime,nattempt,npeop,nbites,m_0,m_1)
          !
          if (MOD(itime,365)==0) then ! Ignore leap years
            !
            ! 3.2) Update population age
            call agents_age(iagent)
            !
          end if
        !
        end do agent_loop
!$OMP END PARALLEL DO
        !
        call agents_diagnostics(disID,scale)  ! Compute bulk stats
        !
        ! Post-diagnostics calculations
        SELECT case(disID)
        case (0) ! Cholera
          !
          ! Scale excretion events to density
          exc(:) = scale(:)*exc(:)
          !
          if (out_rain) then
            exc_clim(:) = scale(:)*exc_clim(:)
          end if
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
        case (1) ! Malaria
          !
          ! Calculate average daily EIR
          EIR(:) = EIR(:)/npeop(:)
          !where(mask_pop(:).and. (npeop(:)>0)) EIR(:) = EIR(:)/npeop(:) !/P_a

          ! Calculate average daily e_l (endemicity level)
          !imm(:) = imm(:)/npeop(:)
          where((mask_pop(:)) .and. (npeop(:)>0)) imm(:) = imm(:)/npeop(:)
          !
        case default
          print *, "Incorrect case, choose disID between: 0 (cholera) and 1 (malaria)"
        STOP
        end SELECT

      end if ! End agent methods -------------------------------------------------
      !
!===
!
end subroutine time_step



end MODULE mo_timestep