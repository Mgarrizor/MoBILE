MODULE mo_agents
! This module contains methods on agents
!
! Authors & Contact
! Adrian M. Tompkins (2014) 
! tompkins@ictp.it

! Miguel Garrido Zornoza (2024)
! mgarrizoraca@gmail.com

USE mo_const
USE mo_control
USE mo_ranlib

USE omp_lib
!use stdlib_stats, only: median

USE, INTRINSIC :: ISO_C_BINDING
!
    implicit none

    ! Variable declarations

    ! Type declarations

    type cholera
        integer :: status   ! S=1, I=2, A=3, R=4
        integer :: infc_dur ! Counter for non-exponentially distributed process
    end type cholera

    type malaria
        integer :: status   ! S=1, E= 2, I=3, A=4, R=5 Susceptible-Exposed-Infected-Asymptomatic-Recovered (SEIAR)
        real    :: EIR_att  ! Entomological inoculation rate
        real    :: hbr_att  ! Human biting rate
        real    :: imm      ! Immunity level [0,1]
        logical :: mat_im   ! Maternal immunity 
       ! real    :: par_load ! Parasite load [Gametocytes/microLiter] 
        integer :: infc_dur ! Infection duration (log-Normal distribution) PfPR ~ 0% (MalariaTheraphy dataset) [ref:m1]
        !                                                                  PfPR ~75% (Ghanaian cohort)         [ref:m2]
    end type malaria

    type dengue 
        integer :: status   ! S=1, E=2, I=3, R=4
        integer :: serotype ! 0,1,2,3,4 Either current serotype (if I/E) or serotype from past infection (if S/R)
        integer :: infc_dur ! Counter for non-exponentially distributed process
    end type dengue

    type active
        logical :: status ! .false.= Dead ; .true.= Alive
    end type active

    type health
        type(active)  :: active_status
        type(cholera) :: cholera_status
        type(malaria) :: malaria_status
        type(dengue)  :: dengue_status

    end type health

    type location
        integer :: homeloc ! xy Default/"home" location
        integer :: currloc ! xy Current location
        integer :: shortloc! xy Fast/short trip location (for now 1)  Models daily contact rates
        integer :: longloc ! xy Long trip location                    Models overnight/long trips, relevant for malaria 
        integer :: longdur ! Number of days the agent has been outside (when moved to longloc)
    end type location

    type agentID
        integer :: name    ! The name of the agent is an integer
        real ::    age     ! Age is a floating-point number
        integer :: sex     ! F/M   [Non-functional]
        integer :: wealth  ! L/M/H [Non-functional]
        real    :: ratio   ! Human to agent ratio of the agent
        real    :: w_NB    ! Weights of the Heterogeneous Poisson model
    end type agentID

    type agent
        type(agentID)  :: agent_ID          ! Who (I am)
        type(location) :: location_status   ! Where (I'm at)
        type(health)   :: health_status     ! What('s my health status)
    end type agent

    ! Array of types (each element is an agent)
    ! "target" for future "slow" mobility using pointers
    type(agent), allocatable, target :: people(:)

    CONTAINS

        subroutine agents_init(nxy,idis,nagent,npeop,nbirths_left,mask_pop,pop_dens,scale,A_cell)
            !
            !
            !
            implicit none
            !
            integer, intent(in) :: idis ! 0 = Cholera: SIAR  ; 1 = Malaria: SEIR [Non-functional]
            integer, intent(in) :: nxy                          !
            integer, intent(in) :: nagent                       !
            integer, allocatable, intent(inout) :: npeop(:)     !
            integer, allocatable, intent(out) :: nbirths_left(:,:) ! (nxy,nthreads) Births left to hand out today, per (cell,thread) -- see mo_const.f90
            real, allocatable, intent(in) :: pop_dens(:)      ! Human population density (len=nxy)
            logical, allocatable, intent(in) :: mask_pop(:)   ! (nxy)

            real, allocatable, intent(inout)   :: A_cell(:)     ! Grid cell area

            real, allocatable, intent(inout) :: scale(:) ! Scale factor to translate number of excretion events into density

            !
            !
            ! Local use only
            integer :: k   ! Dummy looping index
            integer :: ixy ! Looping long index
            integer :: ipeo, indx, loc
            integer :: nthreads, ithread_init ! Thread count and this agent's owning thread (see npeop_thread, mo_const.f90)
            real :: norm, norm_check, rand
            integer :: nfaces
            real, allocatable :: cdf_health(:) ! Cumulative distribution to asign agent health based on initial profile
            real :: cdf(nxy)      ! Cumulative distribution to asign agent location based on human density
            integer :: stat_health
#ifdef MOBILITY
            integer :: j          ! Short trip location index
#endif

            !
            ! Note: this used to call random_seed() here with no arguments, which draws
            ! a fresh seed from the system clock -- meaning every simulation drew a
            ! different series of random numbers, even for two runs of the same
            ! namelist. The random number generator is now seeded once, deterministically,
            ! from the namelist `seed`, at program start (see agents_seed_threads,
            ! called from mobile.f90) -- do not reseed here or the run stops being
            ! reproducible.

            ! Calculate number of agents per grid cell for a given total, nagent, and
            ! the input human population density, pop_dens
            !
            norm_check = sum(pop_dens(:)*A_cell(:)) ! Weighted by cell area
            norm = sum(log(pop_dens(:)*A_cell(:)+1.)) ! Re-scaled weights
            !
            allocate(scale(nxy))
            allocate(scaleI(nxy))
            !
            scale(:)  = norm_check/(A_cell(:)*nagent)
            scaleI(:) = 1./scale(:)
            print *, 'Average scale factor = ', sum(scale(:))/size(scale(:))
            print *, 'Number of people in simulated region', norm_check
            !
            if (norm_check < nagent) then
                print *, 'More agents than people! --> STOP'
                STOP 
            end if 
            !
            P_a = norm_check/nagent
            !
            ! Initialize array of types "agent" -- sized to nagent_max (>=
            ! nagent) so growth-capacity reserve slots exist from the start.
            allocate(people(nagent_max))
            ! Allocate array of the number of agents in each grid cell
            allocate(npeop(nxy))
            npeop(:) = 0
            ! Per-thread breakdown of npeop (see mo_const.f90) -- filled in
            ! below, as each agent is created, using the same thread formula
            ! the daily agent_loop schedule uses.
            nthreads = omp_get_max_threads()
            allocate(npeop_thread(nxy,nthreads))
            npeop_thread(:,:) = 0
            ! Full (dead+alive) capacity per (cell,thread) -- accumulated
            ! incrementally below at every creation site (active or
            ! inactive reserve), unlike npeop_thread which only counts
            ! active agents.
            allocate(nslots_thread(nxy,nthreads))
            nslots_thread(:,:) = 0
            ! Allocate array of the human to agent ratio
            allocate(HA(nxy))
            HA(:) = 0.
            ! Allocate births-remaining-today array. Zeroed here since
            ! agents_pre_diagnostics skips setting it during spin-up (see
            ! in_spinup, mo_control.f90) -- claim sites must never read
            ! uninitialized memory on spin-up's first day.
            allocate(nbirths_left(nxy,nthreads))
            nbirths_left(:,:) = 0
            !
            ! CDF for initial health status
            if (random) then
                !
                if (disID == 0) then
                    nfaces = 4  ! SEIR
                    allocate(cdf_health(nfaces))
                    !
                else if (disID == 1) then 
                    nfaces = 5  ! SEIAR
                    allocate(cdf_health(nfaces))
                    !
                end if
                !
                cdf_health(:) = cumsum([(1./nfaces,k=1,nfaces)])
                !
            else ! Follow initial condition profile
                
            end if
            !
            ! CDF for age distribution





            !
            ! Need an index to keep track of agents
            indx = 1
            do ixy = 1,nxy
                write(*,'(1a1,A19,F6.1,A2)', advance='no') char(13),'Initializing agents',(real(ixy)/real(nxy)*100.),' %'
                if ((mask_pop(ixy))) then ! If area is populated or not missing (FillValue)
                    !
                    ! Standard agent distribution:
                    ! Calculate number of agents in ixy as the fraction of the total 
                    ! population at ixy times the total number of agents
                    !npeop(ixy) = floor(pop_dens(ixy)*(A_cell(ixy))/norm*nagent)
                    
                    !npeop(ixy) = min( floor(pop_dens(ixy)*(A_cell(ixy))/norm*nagent),int(pop_dens(ixy)*A_cell(ixy)) ) ! - Rounding error from floor() function is big, we correct later.
                                                                                                                 ! - Apply min() function to avoid having more agents
                                                                                                                 !   than people.
                    ! Re-scaled agent distribution:
                    ! Weights are now proportional to the natural logarithm of the
                    ! number of agents in each location. This emphasizes low density
                    ! areas, as we need as many agents as we can to resolve the
                    ! different atribute (age, sex, wealth) distributions. This choice 
                    ! is made when the standard method would require a prohibitive number of
                    ! agents, e.g., when run at regional scales.
                    npeop(ixy) = min( ceiling(log(pop_dens(ixy)*A_cell(ixy)+1.)/norm*nagent),int(pop_dens(ixy)*A_cell(ixy)) )
                    !
                    if (npeop(ixy) /= 0) then ! If there is someone
                        do ipeo = 1,npeop(ixy)
                            !
                            ! Initialize main agent attributes
                            people(indx)%agent_ID%age=find_face0(generate_random(),age_weights(:),size(age_weights(:))) &
                                                      + generate_random()
                            age_counts(floor(people(indx)%agent_ID%age)) = age_counts(floor(people(indx)%agent_ID%age)) + 1
                            people(indx)%agent_ID%name=indx     !
                            people(indx)%agent_ID%sex=0         ! F = 0, M = 1 [Not in use]
                            people(indx)%agent_ID%wealth=0      ! L = 0, M = 1, H = 2 [Not in use]
                            people(indx)%agent_ID%w_NB=gengam(k_NB,k_NB)
                            ! Initialize health attributes
                            if (random .and. (.not. rand_seed)) then

                                call random_number(rand)
                                stat_health = find_face(rand,cdf_health(:),nfaces)
                                !
                                if (idis == 1) then
                                    !  
                                    people(indx)%health_status%malaria_status%imm = 0.5
                                    people(indx)%health_status%malaria_status%mat_im = .false. ! No agents initialised with maternal immunity (acquired during spin up)
                                    !
                                    if (stat_health == 1) then !(Susceptible)
                                        !
                                        people(indx)%health_status%malaria_status%infc_dur=0
                                        !
                                    else if (stat_health == 2) then !(Exposed)
                                        !
                                        people(indx)%health_status%malaria_status%infc_dur=iip
                                        !
                                    else if (stat_health == 3) then !(Symptomatic)
                                        ! Log-normally distributed times - function of imm
                                        people(indx)%health_status%malaria_status%infc_dur=tau_log(people(indx)%health_status%malaria_status%imm,d_mu,mu_1,d_sig,sig_1)
                                        !
                                    else if (stat_health == 4) then !(Asymptomatic)
                                        !
                                        ! Chronic asymptomatics
                                        if (generate_random() < fA_chr) then 
                                             !
                                             people(indx)%health_status%malaria_status%infc_dur=tau_chr
                                             !
                                        else 
                                             ! Log-normally distributed times - function of imm
                                             people(indx)%health_status%malaria_status%infc_dur=tau_log(people(indx)%health_status%malaria_status%imm,d_mu,mu_1,d_sig,sig_1)
                                             !
                                         end if
                                    end if
                                end if
                                !
                            else 
                                !
                                stat_health = 1 !(Susceptible)
                                people(indx)%health_status%malaria_status%infc_dur=0
                                !
                                if (idis == 1) then  ! For malaria we generate a low percentage of chronic asymptomatics
                                    if (generate_random() < fA_chr) then 
                                        !
                                        stat_health = 4 !(Asymptomatic)
                                        people(indx)%health_status%malaria_status%infc_dur=tau_chr
                                        !
                                    end if
                                end if
                                !
                            end if
                            ! Cholera
                            people(indx)%health_status%cholera_status%status=stat_health !(S:1, I:2, A:3, R:4)
                            people(indx)%health_status%cholera_status%infc_dur=0
                            ! Malaria
                            people(indx)%health_status%malaria_status%status=stat_health !(S:1, E:2, I:3, A:4, R:5)
                            people(indx)%health_status%active_status%status=.true.       ! All agents are initially alive

                            ! Initialize location attributes
                            people(indx)%location_status%homeloc=ixy
                            people(indx)%location_status%currloc=ixy
                            !
#ifdef MOBILITY
                            ! Short/daily contact rates [non-functional --> wait for Marie-Curie]
                            call random_number(rand) ! Asign visiting location based on mobility scheme
                            j = find_masked_face(rand,Q_short(:,ixy),nxy,mask_grav(:,ixy),mask_pop(:)) ! If agent is mobile j /= 0
                            !
                            people(indx)%location_status%shortloc=j
                            !
                            ! Long overnight trips [non-functional --> wait for Marie-Curie]
                            call random_number(rand) ! Asign long term trips based on mobility scheme
                            j = find_masked_face_2(rand,Q_long(:,ixy),nxy,mask_pop(:)) ! If agent is mobile j /= 0

                            people(indx)%location_status%longloc=j
                            people(indx)%location_status%longdur=0
#endif
                            ! This agent's owning thread for the rest of the run
                            ! (see npeop_thread, mo_const.f90) -- must match the
                            ! agent_loop schedule in mo_timestep.f90 exactly.
                            ithread_init = mod((indx-1)/agent_chunk, nthreads) + 1
                            npeop_thread(ixy,ithread_init) = npeop_thread(ixy,ithread_init) + 1
                            nslots_thread(ixy,ithread_init) = nslots_thread(ixy,ithread_init) + 1
                            indx = indx + 1
                            !
                        end do
                    end if
                    !
                end if
            end do
            !
            ! Correct for previous rounding error -->
            ! Continue asigning based on density until actual number of agents matches nagent,
            ! i.e., until sum(npeop(:)) = nagent = (indx - 1).
            !
            ! Standard distribution of agents:
            ! For this, build a biased dice (see functions below) with weights 
            ! prop. to pop_dens(:)*A_cell(:) and throw it.
            !
            norm = sum(max(pop_dens(:)*A_cell(:)-npeop(:), 0.)) ! Weighted by cell area
            cdf(:) = cumsum(max(pop_dens(:)*A_cell(:)-npeop(:), 0.))/norm
            !
            ! Re-scaled distribution of agents:
            ! Add the correction factor "-npeop(:)" to avoid having a human/agent ratio
            ! bigger than 1. Agents will no distributed to places where the ratio is
            ! smaller than one.
            !
            !norm = sum(log(max(pop_dens(:)*A_cell(:)-npeop(:), 0.)+1.)) ! Re-scaled weights
            !cdf(:) = cumsum(log(max(pop_dens(:)*A_cell(:)-npeop(:), 0.)+1.))/norm !
            !
            !
            !
            write(*,*) ' ' 
            print *, indx, '/ ', nagent
            do while (indx /= (nagent+1))
               !
               call random_number(rand)        ! Throw the dice
               !
               ! Location of new agent
               loc = find_face(rand,cdf(:),nxy)   ! Which face of the dice is it?
               ! 
               if ((mask_pop(loc))) then       ! Safety check (although prob. is zero for unpopulated)
                   npeop(loc) = npeop(loc) + 1
                   !
                   ! Initialize main agent attributes
                   people(indx)%agent_ID%age=find_face0(generate_random(),age_weights(:),size(age_weights(:))) &
                                             + generate_random() ! Selection of year following age structure, and 
                                                                 ! selection of day from uniform distribution
                   age_counts(floor(people(indx)%agent_ID%age)) = age_counts(floor(people(indx)%agent_ID%age)) + 1
                   people(indx)%agent_ID%name=indx     !
                   people(indx)%agent_ID%sex=0         ! F = 0, M = 1
                   people(indx)%agent_ID%wealth=0      ! L = 0, M = 1, H = 2
                   people(indx)%agent_ID%w_NB=gengam(k_NB,k_NB)
                   !
                   ! Initialize health attributes
                   if (random .and. (.not. rand_seed)) then
                       call random_number(rand)
                       stat_health = find_face(rand,cdf_health(:),nfaces)
                       !
                       if (idis == 1) then
                           !  
                           !  
                           people(indx)%health_status%malaria_status%imm = 0.5
                           people(indx)%health_status%malaria_status%mat_im = .false.
                           !
                           if (stat_health == 1) then !(Susceptible)
                               !
                               people(indx)%health_status%malaria_status%infc_dur=0
                               !
                           else if (stat_health == 2) then !(Exposed)
                               !
                               people(indx)%health_status%malaria_status%infc_dur=iip
                               !
                           else if (stat_health == 3) then !(Symptomatic)
                               ! Log-normally distributed times - function of imm
                               people(indx)%health_status%malaria_status%infc_dur=tau_log(people(indx)%health_status%malaria_status%imm,d_mu,mu_1,d_sig,sig_1)
                               !
                           else if (stat_health == 4) then !(Symptomatic)
                               !
                               ! Chronic asymptomatics
                               if (generate_random() < fA_chr) then 
                                    !
                                    people(indx)%health_status%malaria_status%infc_dur=tau_chr
                                    !
                               else 
                                    ! Log-normally distributed times - function of imm
                                    people(indx)%health_status%malaria_status%infc_dur=tau_log(people(indx)%health_status%malaria_status%imm,d_mu,mu_1,d_sig,sig_1)
                                    !
                                end if
                           end if
                       end if
                       !
                   else 
                        !
                        stat_health = 1 !(Susceptible)
                        people(indx)%health_status%malaria_status%infc_dur=0
                        !
                        if (idis == 1) then  ! For malaria we generate a low percentage of chronic asymptomatics (10%)
                            if (generate_random() < fA_chr) then 
                                !
                                stat_health = 4 !(Asymptomatic)
                                people(indx)%health_status%malaria_status%infc_dur=tau_chr
                                !
                            end if
                        end if
                        !
                   end if
                   ! Cholera
                   people(indx)%health_status%cholera_status%status=stat_health !(S:1, I:2, A:3, R:4)
                   people(indx)%health_status%cholera_status%infc_dur=0
                   ! Malaria
                   people(indx)%health_status%malaria_status%status=stat_health !(S:1, E:2, I:3, R:4)

                   !
                   people(indx)%health_status%active_status%status=.true.       ! All agents are initially alive
                   !
                   ! Initialize location attributes (for now only home is functional)
                   people(indx)%location_status%homeloc=loc
                   people(indx)%location_status%currloc=loc
                   !
                   !
#ifdef MOBILITY
                   ! Short/daily contact rates [non-functional --> wait for Marie-Curie]
                   j = find_masked_face(rand,Q_short(:,loc),nxy,mask_grav(:,loc),mask_pop(:)) ! If agent is mobile j /= 0
                   !
                   people(indx)%location_status%shortloc=j   
                   !
                   ! Long overnight trips [non-functional --> wait for Marie-Curie]
                   call random_number(rand) ! Asign long term trips based on mobility scheme
                   j = find_masked_face_2(rand,Q_long(:,loc),nxy,mask_pop(:)) ! If agent is mobile j /= 0
   
                   people(indx)%location_status%longloc=j
                   people(indx)%location_status%longdur=0
#endif
                   !
                   ! This agent's owning thread for the rest of the run (see
                   ! npeop_thread, mo_const.f90) -- must match the agent_loop
                   ! schedule in mo_timestep.f90 exactly.
                   ithread_init = mod((indx-1)/agent_chunk, nthreads) + 1
                   npeop_thread(loc,ithread_init) = npeop_thread(loc,ithread_init) + 1
                   nslots_thread(loc,ithread_init) = nslots_thread(loc,ithread_init) + 1
                   indx = indx + 1
               end if
               !
            end do
            !
            ! Extra growth-capacity slots (nagent+1..nagent_max): distributed
            ! proportional to the just-finished real population npeop(:) --
            ! no cap, unlike the two loops above, since these represent
            ! future, not-yet-existing people, not today's real population.
            ! Created inactive; become active later via the same birth-claim
            ! mechanism (nbirths_left) as any other dead slot.
            if (nagent_max > nagent) then
                cdf(:) = cumsum(real(npeop(:)))/real(nagent)
                do while (indx /= (nagent_max+1))
                    call random_number(rand)
                    loc = find_face(rand,cdf(:),nxy)
                    if (mask_pop(loc)) then
                        people(indx)%agent_ID%age = 0.
                        people(indx)%agent_ID%name = indx
                        people(indx)%agent_ID%sex = 0
                        people(indx)%agent_ID%wealth = 0
                        people(indx)%agent_ID%w_NB = gengam(k_NB,k_NB)
                        people(indx)%health_status%cholera_status%status = 1
                        people(indx)%health_status%cholera_status%infc_dur = 0
                        people(indx)%health_status%malaria_status%status = 1
                        people(indx)%health_status%active_status%status = .false. ! Inactive reserve slot
                        people(indx)%location_status%homeloc = loc
                        people(indx)%location_status%currloc = loc
                        !
                        ithread_init = mod((indx-1)/agent_chunk, nthreads) + 1
                        nslots_thread(loc,ithread_init) = nslots_thread(loc,ithread_init) + 1
                        indx = indx + 1
                    end if
                end do
            end if
            !
            ! npeop_init(:) is active-only (unlike nslots_thread, the full
            ! nagent_max capacity) -- it's the denominator of active_pop_dens
            ! in agents_pre_diagnostics and must reflect today's real
            ! population, not future growth capacity.
            allocate(npeop_init(nxy))
            npeop_init(:) = sum(npeop_thread(:,:), dim=2)
            !
            ! Assign human to agent ratio once all agents have been initialised
            !
            where((pop_dens(:) > 0.) .and. (npeop(:) > 0)) HA(:) = pop_dens(:)*A_cell(:)/npeop(:)
            !HA(:) = pop_dens(:)*A_cell(:)/npeop(:)
            !
            ! Conversion factor between number of agents and density
            !scale(:) = HA(:)/A_cell(:)
            !
            !
            write(*,*) ' '
            print *, 'Check normalization of agents', sum(HA(:)*npeop(:)/norm_check, mask=((pop_dens(:) > 0.) .and. (npeop(:) > 0))), '~ 1?' !& 
                                                             ! /sum(merge(1, 0, mask_pop(:)), mask=((pop_dens(:) > 0.) .and. (npeop(:) > 0))), '~ 1?'
            !
            print '("Initialized:", I8, A8)', nagent, '  agents'
            !
            print *, 'Standard human to agent ratio ~', P_a
            print *, 'Human to agent ratio with re-scaled weights'
            !print *, 'Median :', median(HA(:)))
            print *, 'Mean: ', sum(HA(:), mask=((pop_dens(:) > 0.) .and. (npeop(:) > 0))) & 
                                /sum(merge(1, 0, mask_pop(:)), mask=((pop_dens(:) > 0.) .and. (npeop(:) > 0)))
            print *, 'Mean scale factor:', sum(HA(:), mask=((pop_dens(:) > 0.) .and. (npeop(:) > 0))) & 
                                /sum(merge(1, 0, mask_pop(:)), mask=((pop_dens(:) > 0.) .and. (npeop(:) > 0))) &
                                /(sum(A_cell(:), mask=((pop_dens(:) > 0.) .and. (npeop(:) > 0))) & 
                                /sum(merge(1, 0, mask_pop(:)), mask=((pop_dens(:) > 0.) .and. (npeop(:) > 0))))
            print *, 'Min.: ', minval(HA(:), mask=(HA > 0.)), ' Max.: ', maxval(HA(:), mask=((pop_dens(:) > 0.) .and. (npeop(:) > 0)))
            !
            !deallocate(A_cell)
        end subroutine agents_init

        ! -----------------------------------------------------------------------
        ! Make a run reproducible: give every OpenMP thread its own private,
        ! repeatable random number stream, so that re-running the model with the
        ! same namelist `seed` and the same number of threads reproduces exactly
        ! the same agent-level decisions (health transitions, mobility choices,
        ! disease-profile draws, ...) and therefore exactly the same output.
        !
        ! Before this subroutine existed, neither random number generator used
        ! by the model could be trusted to repeat a run:
        !   - RNGLIB (the library behind gengam, the agent inter-event-time
        !     sampler) had no per-thread state at all: every thread shared the
        !     same "which generator am I" index, so which thread ran first was
        !     free to change the outcome -- a genuine race, not only a
        !     reproducibility gap (see the THREADPRIVATE fix in mo_rnglib.f90).
        !   - The intrinsic random number generator (RANDOM_NUMBER, used almost
        !     everywhere else) was being reseeded from the system clock once at
        !     agent start-up and again on every single simulated day, so two
        !     runs of the same namelist never drew the same numbers.
        !
        ! This subroutine must be called exactly once, early in the run
        ! (mobile.f90), before the model's first daily !$OMP PARALLEL DO
        ! (mo_timestep.f90). OpenMP guarantees that thread-private state set up
        ! here survives every later re-entry into that parallel loop, as long as
        ! the number of threads stays fixed and OMP_DYNAMIC stays off for the
        ! rest of the run -- which is exactly what is enforced below.
        ! -----------------------------------------------------------------------
        subroutine agents_seed_threads(master_seed)

            implicit none
            integer, intent(in) :: master_seed   ! Namelist `seed`: same value everywhere below -> same run
            !
            ! Local use only
            integer :: ithread                   ! OpenMP thread number (0 .. number of threads - 1)
            integer :: n_seed                     ! Length of the seed array RANDOM_SEED expects (compiler-dependent)
            integer :: k                          ! Dummy looping index
            integer, allocatable :: put_seed(:)   ! Seed array handed to RANDOM_SEED(put=...)

            ! Fix the thread count for the rest of the run: OpenMP's guarantee that
            ! thread-private state survives across separate parallel regions only
            ! holds when the number of threads does not change mid-run.
            call omp_set_dynamic(.false.)

            if (omp_get_max_threads() > 32) then
                print *, 'RNGLIB supports at most 32 independent generators --> STOP'
                STOP
            end if

            ! Seed the serial-mode RNG state directly, outside any parallel region.
            ! Code that runs serially (e.g. agents_init, called right after this
            ! subroutine) executes on the master thread, but its RNG storage is not
            ! guaranteed to be the same slot gfortran uses for "thread 0 inside a
            ! team" below -- so both need seeding, with the same formula (ithread=0).
            call random_seed( size = n_seed )
            allocate( put_seed(n_seed) )
            put_seed(:) = master_seed + 104729 + [ (k, k = 1, n_seed) ]
            call random_seed( put = put_seed )
            deallocate( put_seed )
            call cgn_set( 1 )   ! RNGLIB generator 1 for the master/serial stream

!$OMP PARALLEL DEFAULT(SHARED) PRIVATE(ithread,n_seed,k,put_seed)
            ithread = omp_get_thread_num()
            ! Serialize the one-time setup itself -- concurrent RANDOM_SEED/cgn_set
            ! calls during initialization are not safe to assume thread-independent,
            ! even though the resulting per-thread state is. This block runs exactly
            ! once per thread, for the whole program, so the cost is negligible.
!$OMP CRITICAL
            call cgn_set( ithread + 1 )                 ! One RNGLIB generator per thread (1..N)
            call random_seed( size = n_seed )
            allocate( put_seed(n_seed) )
            ! 104729 (the 10 000th prime) only decorrelates the per-thread seed
            ! words deterministically -- no statistical-quality requirement beyond
            ! "different threads get different, repeatable seeds" is needed here.
            put_seed(:) = master_seed + (ithread + 1) * 104729 + [ (k, k = 1, n_seed) ]
            call random_seed( put = put_seed )
            deallocate( put_seed )
!$OMP END CRITICAL
!$OMP END PARALLEL
        end subroutine agents_seed_threads

        subroutine agents_read_age(age_weights,age_counts)
        !===
            ! Reads file 'cumm_age.txt' into an array
            !
            implicit none
            real, allocatable, intent(out) :: age_weights(:)
            integer, allocatable, intent(out) :: age_counts(:)

            ! Local use only
            real :: dummy(100)
            integer :: num_elements
            integer :: i, io_status

            ! Open the file ; status = 'old' means the file must already exist
            OPEN(UNIT=10, FILE='age_structure/cumm_age.txt', STATUS='OLD', ACTION='READ')

            !Read the numbers into the array
            num_elements = 0
            do
                READ(UNIT=10, FMT=*, IOSTAT=io_status) dummy(num_elements + 1)
                if (io_status /= 0) then
                    EXIT
                end if
                num_elements = num_elements + 1
                ! Optional: Check for array overflow
                if (num_elements >= size(dummy)) then
                   print *, "Warning: The age array is full. Some data may not have been read."
                   EXIT
                end if
            end do
            ! Close the file
            CLOSE(UNIT=10)

            allocate(age_weights(num_elements))
            allocate(age_counts(0:num_elements-1))
            allocate(Iage_stat_ptr(8,num_elements)) ! SEIAR = 5 + imm + N(a) + Inew(a)
            !
            age_counts(:) = 0
            do i = 1, num_elements
                age_weights(i) = dummy(i)
            end do
            WRITE(*,*) '=========================='
            WRITE(*,*) 'Age weights'
            WRITE(*, '(5F8.4)') age_weights
            WRITE(*,*) '=========================='

        end subroutine agents_read_age

        subroutine agents_update_age_counts()
        !===
            ! Rebuilds age_counts(:) from the live population (called yearly,
            ! see mobile.f90) -- same floor(age) binning as the init-time
            ! count, but scanning 1..nagent_max and filtering to active
            ! agents, since growth-reserve slots (nagent+1..nagent_max) are
            ! inactive until claimed via a birth.
            implicit none
            integer :: k, abin

            age_counts(:) = 0
            do k = 1, nagent_max
                if (people(k)%health_status%active_status%status) then
                    abin = min(floor(people(k)%agent_ID%age), size(age_weights)-1)
                    age_counts(abin) = age_counts(abin) + 1
                end if
            end do
        end subroutine agents_update_age_counts

        subroutine agents_diagnostics(idis,iagent)
        !===
            ! Calculate bulk statistics to feed into the disease source integration
            !
            integer, intent(in) :: idis ! 0 = Cholera: SIAR  ; 1 = Malaria: SEIAR ; 2 = Dengue [Non-functional]
            integer, intent(in) :: iagent ! Agent ID (integer number)
            !
            ! Local use only
            integer :: istat, iloc, iage, ithread
            logical :: iactive

            ! Per-thread private column: lock-free writes here, merged into the
            ! shared arrays once a day in agents_post_diagnostics.
            ithread = omp_get_thread_num() + 1

            SELECT case(idis)
            case (0) ! Cholera -------------------------------
            !
            ! Increase age by da = 1/365 -- held fixed during spin-up (see
            ! in_spinup, mo_control.f90) so the day-0 age structure isn't
            ! shifted by however many years spin-up takes to converge.
            if (.not. in_spinup) then
                people(iagent)%agent_ID%age =  people(iagent)%agent_ID%age + da
            end if
            !
            istat    =  people(iagent)%health_status%cholera_status%status
            iactive  =  people(iagent)%health_status%active_status%status
            iloc     =  people(iagent)%location_status%currloc
            !
            ! Pointer approach to allow vectorization (discarded old branching if ... elseif ...)
            if (iactive) then
                status_pointer(istat)%arr_p_priv(iloc,ithread) = &
                status_pointer(istat)%arr_p_priv(iloc,ithread) + 1.
            end if
            !
            !=================================================

            !
            case (1) ! Malaria -------------------------------
            !
            ! Increase age by da = 1/365 -- held fixed during spin-up (see
            ! in_spinup, mo_control.f90) so the day-0 age structure isn't
            ! shifted by however many years spin-up takes to converge.
            if (.not. in_spinup) then
                people(iagent)%agent_ID%age =  people(iagent)%agent_ID%age + da
            end if
            !
            istat   =  people(iagent)%health_status%malaria_status%status
            iactive =  people(iagent)%health_status%active_status%status
            iloc    =  people(iagent)%location_status%currloc
            iage    =  min(floor(people(iagent)%agent_ID%age),79)
            !
            ! Pointer approach to allow vectorization (discarded old branching if ... elseif ...)
            if (iactive) then
                ! bulk SEIAR
                status_pointer(istat)%arr_p_priv(iloc,ithread) = &
                status_pointer(istat)%arr_p_priv(iloc,ithread) + 1.
                !
                if (in_imm) then ! Immunity is set to that of the external forcing
                    !
                    people(iagent)%health_status%malaria_status%imm = imm(iloc)
                    !
                else ! Otherwise we gather value from agent for diagnostics
                    imm_priv(iloc,ithread) = imm_priv(iloc,ithread) + &
                    people(iagent)%health_status%malaria_status%imm
                end if
                !
                if (diag_age) then
                    ! Symptomatic/asymptomatic disaggregated by age (S/E/R by
                    ! age have no output flag and no reader -- not staged).
                    if (istat == 3 .or. istat == 4) then
                        Iage_stat_ptr(istat,iage+1)%arr_p_priv(iloc,ithread) = &
                        Iage_stat_ptr(istat,iage+1)%arr_p_priv(iloc,ithread) + 1.
                    end if
                    !
                    ! Immunity disaggregated by age
                    Iage_stat_ptr(6,iage+1)%arr_p_priv(iloc,ithread) = &
                    Iage_stat_ptr(6,iage+1)%arr_p_priv(iloc,ithread) + &
                    people(iagent)%health_status%malaria_status%imm
                    !
                    ! Agent number disaggregated by age
                    Iage_stat_ptr(7,iage+1)%arr_p_priv(iloc,ithread) = &
                    Iage_stat_ptr(7,iage+1)%arr_p_priv(iloc,ithread) + 1.
                    !
                    ! Inew and Inew(a) are updated on the spot
                end if
            end if
            !
            EIR_priv(iloc,ithread) = EIR_priv(iloc,ithread) + &
            people(iagent)%health_status%malaria_status%EIR_att
            hbr_priv(iloc,ithread) = hbr_priv(iloc,ithread) + &
            people(iagent)%health_status%malaria_status%hbr_att
            !===================================================
            !
            case (2) ! Dengue [Non-functional]
            !
            case default
                print *, "Dengue [Non-functional] - choose disID between: 0 (cholera) & 1 (malaria)"
                STOP
            end SELECT
            !
        !===
        end subroutine agents_diagnostics

        subroutine agents_pre_diagnostics(idis,itime)
        !===
            ! Calculate bulk statistics to feed into the disease source integration
            !
            integer, intent(in) :: idis ! 0 = Cholera: SIAR  ; 1 = Malaria: SEIAR ; 2 = Dengue [Non-functional]
            integer, intent(in) :: itime ! Current time step
            !
            ! Local use only
            integer :: ixy, m, t   ! Looping spatial/status/thread indices
            integer :: n_tot       ! Today's total ticket draw for one cell
            integer :: remaining   ! Tickets not yet handed to a thread
            integer :: dead_t      ! Thread t's current dead-slot capacity in this cell
            real :: b_t             ! Today's birth rate, interpolated from birth_years/birth_vals
            real :: active_pop_dens(nxy) ! pop_dens(:) scaled by today's active-agent fraction (malaria only)
            !
            ! Draw today's total births per cell, then hand tickets to threads
            ! in a fixed order up to each thread's own dead-slot capacity
            ! (nslots_thread-npeop_thread, see mo_const.f90) -- a ticket only
            ! goes unclaimed when the whole cell is out of dead slots. Dead
            ! slots claim from their own thread's column (lock-free) in
            ! agents_malaria/agents_cholera. Skipped entirely during spin-up
            ! (see in_spinup, mo_control.f90) so the population/age structure
            ! stays fixed at day-0 values while spin-up equilibrates immunity.
            if (.not. in_spinup) then
                b_t = interp1(real(itime-1)*da, birth_years, birth_vals)
                do ixy = 1, nxy
                    if (mask_pop(ixy)) then
                        n_tot = ignbin(npeop(ixy), b_t)
                        remaining = n_tot
                        do t = 1, size(nbirths_left,dim=2)
                            dead_t = nslots_thread(ixy,t) - npeop_thread(ixy,t)
                            nbirths_left(ixy,t) = min(remaining, dead_t)
                            remaining = remaining - nbirths_left(ixy,t)
                        end do
                    end if
                end do
            end if
            !
            SELECT case(idis)
            case (0) ! Cholera -------------------------------
            ! Reset base excretion array
            exc(:) = 0.
            !
            ! Reset rainfall-driven excretion array
            if (out_rain) then
              exc_clim(:) = 0.
            end if
            !
            !
            S(:) = 0.
            I(:) = 0.
            A(:) = 0.
            R(:) = 0.
            !
            ! Reset per-thread staging columns (agents_diagnostics writes here lock-free)
            do m = 1, 4 ! SIAR
                status_pointer(m)%arr_p_priv(:,:) = 0.
            end do
            !
            !=================================================
            !
            case (1) ! Malaria -------------------------------
            !
            ! Reset number of infective bites
            nbites(:) = 0
            !
            ! Compute base interaction rates
            !
            ! active_pop_dens(:) scales the reference density pop_dens(:) by
            ! today's active-agent fraction, so vector-bite saturation below
            ! reflects live agents, not dead slots. Kept as an explicit
            ! factor on pop_dens(:) -- not folded into the init-time-fixed
            ! HA(:) -- so pop_dens(:) can later become a time-varying growth
            ! profile without these formulas changing.
            where ((pop_dens(:) > 0.) .and. (npeop(:) > 0))
                active_pop_dens(:) = pop_dens(:)*real(npeop(:))/real(npeop_init(:))
                ! Human to vector transmission
                m_0(:) = b_rate*rgonof(:)*rvect(0,:)/(active_pop_dens(:)+K_h)*HA(:)
                ! Infected vector to human transmission
                m_1(:) = b_rate*rgonof(:)*rvect(ninfv,:)/(active_pop_dens(:)+K_h)*HA(:)
                ! All vector to human (human biting rate - hbr)
                m_all(:) = b_rate*rgonof(:)*SUM(rvect(:,:), DIM=1)/(active_pop_dens(:)+K_h)*HA(:)
            end where
            !
            S(:) = 0.
            E(:) = 0.
            I(:) = 0.
            I_new(:) = 0.
            A(:) = 0.
            R(:) = 0.
            !
            EIR(:) = 0.
            if (.not. in_imm) then ! If not external forcing then reset immunity
                !
                imm(:) = 0.
                !
            end if
            hbr(:) = 0.
            !
            if (diag_age) then
                Sa(:,:) = 0.
                Ea(:,:) = 0.
                Ia(:,:) = 0.
                Ia_new(:,:) = 0.
                Aa(:,:) = 0.
                Ra(:,:) = 0.

                imm_a(:,:) = 0.
                N_a(:,:)   = 0.
            end if
            !
            ! Reset per-thread staging columns (agents_diagnostics/agents_malaria
            ! write here lock-free; merged in agents_post_diagnostics)
            do m = 1, 6 ! SEIAR(a) + i_m(a) + N(a)
                status_pointer(m)%arr_p_priv(:,:) = 0.
            end do
            EIR_priv(:,:) = 0.
            hbr_priv(:,:) = 0.
            if (.not. in_imm) then
                imm_priv(:,:) = 0.
            end if
            if (diag_age) then
                ! Reset directly (one shot per BLOCK), not per exact age --
                ! Iage_stat_ptr(:,iage)%arr_p_priv aliases these same arrays.
                ! Sa/Ea/Ra have no output flag and no reader -- not staged.
                Ia_priv(:,:,:) = 0.
                Aa_priv(:,:,:) = 0.
                imm_a_priv(:,:,:) = 0.
                N_a_priv(:,:,:) = 0.
                Ia_new_priv(:,:,:) = 0.
            end if
            !
            !===================================================
            !
            case (2) ! Dengue [Non-functional]
            !
            case default
                print *, "Incorrect case, choose disID between: 0 (cholera) & 1 (malaria)"
                STOP
            end SELECT
            !
        !===
        end subroutine agents_pre_diagnostics

        subroutine agents_post_diagnostics(idis)
        !===
            ! Calculate bulk statistics to feed into the disease source integration
            !
            integer, intent(in) :: idis ! 0 = Cholera: SIAR  ; 1 = Malaria: SEIAR ; 2 = Dengue [Non-functional]
            !integer, intent(in) :: iagent ! Agent ID (integer number)
            !real, allocatable, intent(in)    :: scale(:)
            !integer, intent(out):: counter ! Number of alive agents
            !
            ! Local use only
            integer :: j
            !integer :: istat, iloc, iage, j
            !logical :: iactive
            !real :: conv1, conv2

            ! npeop(:) is derived, not written directly -- see npeop_thread,
            ! mo_const.f90.
            npeop(:) = sum(npeop_thread(:,:), dim=2)

            SELECT case(idis)
            case (0) ! Cholera -------------------------------
            !
            ! Merge per-thread staging columns into the shared arrays before
            ! normalizing below.
            S(:) = S(:) + sum(status_pointer(1)%arr_p_priv(:,:), dim=2)
            I(:) = I(:) + sum(status_pointer(2)%arr_p_priv(:,:), dim=2)
            A(:) = A(:) + sum(status_pointer(3)%arr_p_priv(:,:), dim=2)
            R(:) = R(:) + sum(status_pointer(4)%arr_p_priv(:,:), dim=2)
            !
            S(:) = S(:)/npeop(:)
            I(:) = I(:)/npeop(:)
            A(:) = A(:)/npeop(:)
            R(:) = R(:)/npeop(:)

            ! Scale excretion events to density
            exc(:) = exc(:)/npeop(:)
            !
            if (out_rain) then
              exc_clim(:) = exc_clim(:)/npeop(:)
            end if
            !
            B_old = B
            A_old = A
            !
            ! Check for demographic convergence (cholera model)
            !conv1 = 0.
            !conv2 = 0.
            !do ixy = 1,nxy
            !  if (mask_pop(ixy)) then
            !      !
            !      conv1 = conv1 + (scale(ixy)*npeop(ixy) - alpha/mu * I(ixy))
            !      conv2 = conv2 + (1+ gamma/(rho+mu))*(I(ixy)+ A(ixy)) + S(ixy)
            !      !
            !  end if
            !end do
            !=================================================

            ! Age-structured

            !=================================================
            case (1) ! Malaria -------------------------------
            !
            ! Merge per-thread staging columns into the shared arrays before
            ! normalizing below.
            S(:) = S(:) + sum(status_pointer(1)%arr_p_priv(:,:), dim=2)
            E(:) = E(:) + sum(status_pointer(2)%arr_p_priv(:,:), dim=2)
            I(:) = I(:) + sum(status_pointer(3)%arr_p_priv(:,:), dim=2)
            A(:) = A(:) + sum(status_pointer(4)%arr_p_priv(:,:), dim=2)
            R(:) = R(:) + sum(status_pointer(5)%arr_p_priv(:,:), dim=2)
            I_new(:) = I_new(:) + sum(status_pointer(6)%arr_p_priv(:,:), dim=2)
            !
            EIR(:) = EIR(:) + sum(EIR_priv(:,:), dim=2)
            hbr(:) = hbr(:) + sum(hbr_priv(:,:), dim=2)
            if (.not. in_imm) then
                imm(:) = imm(:) + sum(imm_priv(:,:), dim=2)
            end if
            !
            if (diag_age) then
                ! Merge once per BLOCK (not per exact age -- Iage_stat_ptr(:,iage)
                ! for ages sharing a block alias the same *_priv column set, so
                ! merging per exact age would double-count shared blocks).
                ! Sa/Ea/Ra have no output flag and no reader -- not merged.
                do j = 1, size(age_blocks(:))
                    Ia(:,j) = Ia(:,j) + sum(Ia_priv(:,:,j), dim=2)
                    Aa(:,j) = Aa(:,j) + sum(Aa_priv(:,:,j), dim=2)
                    imm_a(:,j) = imm_a(:,j) + sum(imm_a_priv(:,:,j), dim=2)
                    N_a(:,j) = N_a(:,j) + sum(N_a_priv(:,:,j), dim=2)
                    Ia_new(:,j) = Ia_new(:,j) + sum(Ia_new_priv(:,:,j), dim=2)
                end do
            end if
            !
            ! Fraction [per person]  = HA*N/(rho*A_cell) = N/npeop - with mobility this will have to
            !                                                        be modified
            S(:) = S(:)/npeop(:)
            E(:) = E(:)/npeop(:)
            I(:) = I(:)/npeop(:)
            I_new(:) = I_new(:)/npeop(:)
            A(:) = A(:)/npeop(:)
            R(:) = R(:)/npeop(:)

            ! Age-structured
            if (diag_age) then
                do j = 1, size(age_blocks(:))
                    !
                    Ia_new(:,j) = Ia_new(:,j)/N_a(:,j)
                    Ia(:,j) = Ia(:,j)/N_a(:,j)
                    Aa(:,j) = Aa(:,j)/N_a(:,j)
                    !
                    imm_a(:,j) = imm_a(:,j)/N_a(:,j)  ! Normalize by number of people in that age group
                    !
                end do
            end if
            !
            ! Calculate average daily EIR on a per person basis (use human to agent ratio: HA(:))
            !
            where((mask_pop(:)) .and. (npeop(:)>0)) EIR(:) = EIR(:)/npeop(:)/HA(:)!P_a!/HA(:)

            ! Calculate average daily hbr
            !
            where((mask_pop(:)) .and. (npeop(:)>0)) hbr(:) = hbr(:)/npeop(:)/HA(:)!P_a!/HA(:)

            ! Calculate average daily imm (immunity level)
            !
            if (.not. in_imm) then
              where((mask_pop(:)) .and. (npeop(:)>0)) imm(:) = imm(:)/npeop(:)
            end if
            !
            !===================================================

            !
            case (2) ! Dengue [Non-functional]
            !
            case default
                print *, "Incorrect case, choose disID between: 0 (cholera) & 1 (malaria)"
                STOP
            end SELECT
            !
        !===
        end subroutine agents_post_diagnostics

        subroutine agents_update(idis,iagent,itime,nbirths_left,npeop,nbites,m_0,m_1,m_all)
        !===
            ! This subroutine updates agent disease and mobility statuses (mobility non-functional - to be implemented if Marie-Curie is funded)
            implicit none

            real, allocatable, intent(in) :: m_0(:)  ! Susceptible vector to host ratio times the vector biting rate
            real, allocatable, intent(in) :: m_1(:)  ! Infective   vector to host ratio times the vector biting rate
            real, allocatable, intent(in) :: m_all(:)  ! Vector to host ratio times the vector biting rate

            integer, intent(in) :: idis              ! Disease ID (0: Cholera, 1: Malaria)
            integer, intent(in) :: iagent            ! Agent ID (integer number)
            integer, intent(in) :: itime             ! Current time step
            integer, allocatable, intent(inout) :: nbirths_left(:,:) ! (nxy,nthreads) Births left to hand out today, per (cell,thread)
            integer, allocatable, intent(inout) :: npeop(:)       ! (nxy) Number of agents in each grid cell
            integer, allocatable, intent(inout) :: nbites(:)      ! (nxy) Infective bites (vectors that were infected upon bitting a human)

            ! *************** Start subroutine *******************
            !
            SELECT case(idis)
            case (0) ! Cholera
            !
            call agents_cholera(iagent,itime,nbirths_left,npeop)
            !
            case (1) ! Malaria
            !
            call agents_malaria(iagent,nbirths_left,npeop,nbites,m_0,m_1,m_all)
            !
            case (2) ! Dengue [Non-functional]
            !
            call agents_dengue()
            !
            case default
                print *, "Incorrect case, choose disID between: 0 (cholera), 1 (malaria)"
                STOP
            end SELECT
        !===
        end subroutine agents_update
        !
        !
        subroutine agents_age(iagent)
        !===
            ! This subroutine updates age of agent "iagent" by one year
            implicit none
            integer, intent(in) :: iagent ! Agent ID
            !
            people(iagent)%agent_ID%age = people(iagent)%agent_ID%age + 1
            !
        !===
        end subroutine agents_age
        !
        !
        subroutine agents_cholera(iagent,itime,nbirths_left,npeop)

            implicit none
            integer, intent(in) :: iagent            ! Agent ID (integer number)
            integer, intent(in) :: itime             ! Time step
            integer, allocatable, intent(inout) :: nbirths_left(:,:) ! (nxy,nthreads) Births left to hand out today, per (cell,thread)
            integer, allocatable, intent(inout) :: npeop(:)        ! (nxy) Number of agents in each grid cell

            ! Local use only
            real :: rand    ! Uniformly distributed random number to throw dices
            integer :: stat ! Agent health status
            integer :: i    ! Agent location
            integer :: j    ! Location where agent moves
            integer :: claimed ! [birth claim] this agent's ticket, if any, from nbirths_left(i,ithread)
            integer :: ithread ! This agent's owning thread -- see npeop_thread, mo_const.f90
            logical :: active ! Is the agent alive?

        ithread = omp_get_thread_num() + 1

        ! Events depend on health status and physical location.
        active =  people(iagent)%health_status%active_status%status
        stat   =  people(iagent)%health_status%cholera_status%status
        i      =  people(iagent)%location_status%currloc

        if (mask_pop(i)) then ! Check if location is populated and driving fields are not missing
                if (active) then  ! If agent is alive
                    !
                    if (stat == 1) then ! If susceptible (S) *****************************
                        !
                        ! Mobility ==========
                        !
                        ! If agent moves
                        if ((generate_random() < m_short) .and. (mask_mob(i))) then ! probability to move = m ; Are you allowed to move? --> mask_mob
                            !call random_number(rand)
                            ! then go to travel location
                            j = people(iagent)%location_status%shortloc
                            !
                            ! Health ============
                            ! Once there, is it in contact with the disease?
                            !
                            if (generate_random() <= beta) then
                                ! If so, it will get infected with prob B/(1+B)
                                !
                                if (generate_random() <= B(j)/(1+B(j))) then
                                    ! Only then we change the agent status S --> I or A 
                                    !
                                    ! Prob. to be symptomatic
                                    if (generate_random() <= sigma) then
                                        people(iagent)%health_status%cholera_status%status=2
                                    ! Else is asymptomatic
                                    else
                                        people(iagent)%health_status%cholera_status%status=3
                                    end if
                                end if
                            end if
                        ! Mobility ==========
                        ! If agent does not move
                        else
                            ! it could be in touch with local disease
                            !
                            ! Health ============
                            !
                            ! Disease
                            if (generate_random() <= beta) then
                                ! when in touch it can get infected
                                call random_number(rand)
                                if ((eps <= rand) .and. (rand <= B(i)/(1+B(i)))) then
                                    ! If infected
                                    !
                                    ! Prob. to be symptomatic
                                    if (generate_random() <= sigma) then
                                        people(iagent)%health_status%cholera_status%status=2
                                    ! Else is asymptomatic
                                    else
                                        people(iagent)%health_status%cholera_status%status=3
                                    end if
                                end if
                            end if
                            !
                        end if
                        ! Base mortality
                        !
                        if (.not. in_spinup) then
                        if (generate_random() <= mu_age(min(floor(people(iagent)%agent_ID%age),79))) then ! Death
                            !
                            people(iagent)%health_status%active_status%status=.false.
                            ! Update this thread's column, not npeop(:) -- npeop(:) is
                            ! derived once/day in agents_post_diagnostics (mo_const.f90).
                            npeop_thread(i,ithread) = npeop_thread(i,ithread) - 1
                            !
                        end if
                        end if ! .not. in_spinup
                    !==    
                    !
                    elseif (stat == 2) then ! If infected (I) *****************************
    
                        ! Mobility ==========
                            ! No mobility if symptomatic
    
                        ! Health ============
                        !
                        ! Recovery I --> R
                        if (generate_random() <= gamma) then
                            people(iagent)%health_status%cholera_status%status=4
                            !
                        ! Death from disease
                        else if (generate_random() <= alpha) then
                            !
                            people(iagent)%health_status%active_status%status=.false.
                            !
                        ! Excretion event
                        else
                            !
                            if (generate_random() <= (theta_e*D(i))) then
                            ! Add counter to excretion array
                                exc(i) = exc(i) + 1
                            else if (out_rain) then
                                !
                                if (generate_random() <= theta_p*D(i)*rainfall(i,itime)) then
                                ! Add counter to climate-driven excretion array
                                    exc_clim(i) = exc_clim(i) + 1
                                end if
                            end if
                            !
                        end if 
                        ! Base mortality
                        !
                        if (.not. in_spinup) then
                        if (generate_random() <= mu_age(min(floor(people(iagent)%agent_ID%age),79))) then ! Death
                            !
                            people(iagent)%health_status%active_status%status=.false.
                            ! Update this thread's column, not npeop(:) -- npeop(:) is
                            ! derived once/day in agents_post_diagnostics (mo_const.f90).
                            npeop_thread(i,ithread) = npeop_thread(i,ithread) - 1
                            !
                        end if
                        end if ! .not. in_spinup
                        ! end Health  
                    !===                  
                    ! 
                    elseif (stat == 3) then ! If asymptomatic (A) *****************************
                        
                        ! Mobility ==========
                        ! If agent moves
                        !
                        call random_number(rand)
                        if ((rand < m_short) .and. (mask_mob(i))) then
                            ! then go to typical short trip location
                            j = people(iagent)%location_status%shortloc 
                            !
                            ! Health ============
                            ! Once there, it cannot be infected, but might contribute to the local load of the disease
                            ! Excretion event
                            !
                            if (generate_random() <= (theta_e*D(j))) then
                            ! Add counter to excretion array
                                !
                                exc(j) = exc(j) + 1
                                !
                            else if (out_rain) then
                                !
                                if (generate_random() <= theta_p*D(j)*rainfall(j,itime)) then
                                    !
                                    exc_clim(j) = exc_clim(j) + 1
                                    !
                                end if
                                !
                            end if
                        ! Mobility ==========
                        ! If agent does not move
                        else
                            ! Health ============
                            ! Local contribution to bacterial load
                            !
                            if (generate_random() <= (theta_e*D(i))) then
                            ! Add counter to excretion array
                                exc(i) = exc(i) + 1
                            !
                            else if (out_rain) then
                                !
                                if (generate_random() <= theta_p*D(i)*rainfall(i,itime)) then
                                    exc_clim(i) = exc_clim(i) + 1
                                end if
                                !
                            end if
                            !
                        end if
                        ! Health ============
                        ! 
                        ! Recovery A --> R
                        if (generate_random() <= gamma) then
                            !
                            people(iagent)%health_status%cholera_status%status=4
                            !
                        end if
                        !
                        ! Base mortality
                        !
                        if (.not. in_spinup) then
                        if (generate_random() <= mu_age(min(floor(people(iagent)%agent_ID%age),79))) then ! Death
                            !
                            people(iagent)%health_status%active_status%status=.false.
                            ! Update this thread's column, not npeop(:) -- npeop(:) is
                            ! derived once/day in agents_post_diagnostics (mo_const.f90).
                            npeop_thread(i,ithread) = npeop_thread(i,ithread) - 1
                            !
                        end if
                        end if ! .not. in_spinup
                    !===  
                    ! 
                    elseif (stat == 4) then ! If recovered (R) *****************************
                        ! Health ============
                        !
                        ! Loss of immunity R --> S
                        if (generate_random() <= rho) then 
                            !
                            people(iagent)%health_status%cholera_status%status=1
                            !
                        end if
                        !
                        ! Base mortality
                        !
                        if (.not. in_spinup) then
                        if (generate_random() <= mu_age(min(floor(people(iagent)%agent_ID%age),79))) then
                            !
                            people(iagent)%health_status%active_status%status=.false.
                            ! Update this thread's column, not npeop(:) -- npeop(:) is
                            ! derived once/day in agents_post_diagnostics (mo_const.f90).
                            npeop_thread(i,ithread) = npeop_thread(i,ithread) - 1
                            !
                        end if
                        end if ! .not. in_spinup
                        !
                    end if 
                else ! If agent is dead
                   !
                   ! nbirths_left(i,ithread) is this thread's own ticket pool for cell i
                   ! (set in agents_pre_diagnostics) -- no ATOMIC needed to claim from it.
                   claimed = nbirths_left(i,ithread)
                   nbirths_left(i,ithread) = nbirths_left(i,ithread) - 1
                   if (claimed > 0) then
                        !
                        people(iagent)%health_status%active_status%status=.true. ! You are now alive,
                        people(iagent)%health_status%cholera_status%status=1     ! born susceptible
                        people(iagent)%agent_ID%age=0.                            ! and as a baby
                        people(iagent)%agent_ID%w_NB=gengam(k_NB,k_NB)
                        !
                        if (generate_random() <= 0.51) then ! Sex
                            people(iagent)%agent_ID%sex=0   ! Female = 0
                        else
                            people(iagent)%agent_ID%sex=1   ! Male = 1
                        end if
                        ! Update this thread's column, not npeop(:) -- npeop(:) is
                        ! derived once/day in agents_post_diagnostics (mo_const.f90).
                        npeop_thread(i,ithread) = npeop_thread(i,ithread) + 1
                   end if
                end if ! If (active)
            end if ! If (mask_pop(currloc))
        !==
        end subroutine agents_cholera
        !
        !
        subroutine agents_malaria(iagent,nbirths_left,npeop,nbites,m_0,m_1,m_all)

            implicit none
            integer, intent(in) :: iagent            ! Agent ID (integer number)
            integer, allocatable, intent(inout) :: nbirths_left(:,:) ! (nxy,nthreads) Births left to hand out today, per (cell,thread)
            integer, allocatable, intent(inout) :: npeop(:)       ! (nxy) Number of agents in each grid cell
            integer, allocatable, intent(inout) :: nbites(:)      ! (nlon*nlat) Infective bites
                                                     ! (vectors that were infected upon
                                                     ! bitting a human)
            real, allocatable, intent(in) :: m_0(:)  ! Susceptible vector to host ratio times the vector biting rate
            real, allocatable, intent(in) :: m_1(:)  ! Infective   vector to host ratio times the vector biting rate
            real, allocatable, intent(in) :: m_all(:)  ! Vector to host ratio times the vector biting rate

            ! Local use only
            integer :: stat ! Agent health status
            integer :: i    ! Agent location
            integer :: j    ! Location where agent moves
            integer :: home ! Home location
            integer :: claimed ! [birth claim] this agent's ticket, if any, from nbirths_left(i,ithread)
            integer :: ithread ! Per-thread private column for I_new/Ia_new staging
            logical :: active ! Is the agent alive?

            ! Disease transmission
            ! 0: Human to vector  1: Vector to human
            !
            real :: lambda_0, lambda_1, lambda_all
            real :: P_0                     ! Human to vector
            real :: P_1                     ! Vector to human


        ! Events depend on health status and physical location.
        active =  people(iagent)%health_status%active_status%status
        stat   =  people(iagent)%health_status%malaria_status%status
        i      =  people(iagent)%location_status%currloc
        home   =  people(iagent)%location_status%homeloc
        ithread = omp_get_thread_num() + 1


        ! ToC ===========================
        !
        ! 1) Mobility [non-functional]
        ! 2) Disease
        !   2.0) Maternal immunity
        !   2.1) Transmission probabilities
        !   2.2) SEIAR update
        !
        !-----------------------------------------------------------------------------

        if (mask_pop(i)) then ! Check if location is populated and driving fields are not missing
                if (active) then  ! If agent is alive
                    !
                    ! Since vector-human interactions are (for now) overnight we can neglect the effect of daily trips
                    ! and therefore treat mobility first and then disease  
                    !
#ifdef MOBILITY
                    ! 1) Mobility [non-functional] ==============================
                    !
                    if (stat /= 3) then ! If not in symptomatic state
                    !===
                        !
                        ! If agent is in longloc
                        if (i /= home) then
                            
                            if ((generate_random() <= r_ret)) then ! Return home with some constant probability 
                                                                   ! (this means we have exponentially distributed travelling times
                                                                   ! with folding time = 1/r_ret)
                                people(iagent)%location_status%currloc = home
                                j = home

                                ! npeop_thread live-updated here (npeop(:) is derived once/day,
                                ! see mo_const.f90); no ATOMIC needed since the same agent/thread
                                ! writes both npeop_thread(i,*) and npeop_thread(j,*) below.
                                npeop_thread(i,ithread) = npeop_thread(i,ithread) - 1
                                npeop_thread(j,ithread) = npeop_thread(j,ithread) + 1
                            else
                                ! Update duration of trip counter --> useful if we implement not exponential travelling times
                                people(iagent)%location_status%longdur = people(iagent)%location_status%longdur + 1

                            end if
                        else 
                            !
                            ! If agent makes a short trip
                            if ((generate_random() < m_short)) then ! probability to move = m_short
                            ! Do not update currloc as this is a daily trip
        
                            !
                            ! If agent makes a long trip
                            elseif ((generate_random() < m_long)) then ! probability to move = m_long
                                
                                j = people(iagent)%location_status%longloc
                                people(iagent)%location_status%currloc = j
                                people(iagent)%location_status%longdur = 1     ! Counter in case trip durations are not exponentially distributed

                                ! npeop_thread live-updated here (npeop(:) is derived once/day,
                                ! see mo_const.f90); no ATOMIC needed since the same agent/thread
                                ! writes both npeop_thread(i,*) and npeop_thread(j,*) below.
                                npeop_thread(i,ithread) = npeop_thread(i,ithread) - 1
                                npeop_thread(j,ithread) = npeop_thread(j,ithread) + 1
                            !
                            ! else agent does not move
                            !
                            end if
                        end if
                        !
                    !===
                    end if
#endif  
                    !
                    ! ! 2) Disease ===========================
                    !
                    ! 2.0) Maternal immunity
                    !
                    if (people(iagent)%health_status%malaria_status%mat_im) then ! If maternal immunity is active it
                        if (generate_random() < mat_rate) then                   ! becomes inactive with a probability = mat_rate
                           !
                            people(iagent)%health_status%malaria_status%mat_im = .false.
                           !
                        end if 
                    end if 
                                                                             !
                    ! 2.1) Transmission probabilities --------
                    !
                    !===
                        ! Get agent location to get local biting rates m(j)
                        j = people(iagent)%location_status%currloc
                        !
                        ! ********** Interventions **************
                        !
                        ! f(a,t) = 1   
                        !
                        !****************************************
                        !
                        ! All-sporogonic-stages biting rate
                        !
                        lambda_all = m_all(j)*1. ! f(a,t) = 1
                        !
                        ! Human to Vector transmission
                        !
                        lambda_0 = m_0(j)*1. ! f(a,t) = 1 
                        !P_0 = P_max*(1 - exp(-lambda_0*P_h0))                              ! Homogeneous Poisson model
                        !P_0 = P_max*(1 - (k_NB/(k_NB+lambda_0*P_h0))**k_NB)                ! Negative Binomial model
                        P_0 = P_max*(1 - exp(-people(iagent)%agent_ID%w_NB*lambda_0*P_h0))  ! Heterogeneous Poisson model
                        !
                        ! Vector to Human transmission
                        !
                        lambda_1 = m_1(j)*1. ! f(a,t) = 1 
                        !P_1 = 1 - exp(-lambda_1*P_v0)                              ! Homogeneous Poisson model
                        !P_1 = 1 - (k_NB/(k_NB+lambda_1*P_v0))**k_NB                ! Negative Binomial model
                        P_1 = 1 - exp(-people(iagent)%agent_ID%w_NB*lambda_1*P_v0)  ! Heterogeneous Poisson model
                        !
                        ! Apply numerical threshold ---> Need to optimize transmission events for cases where P < epsilon
                        P_0 = min(real(floor(P_0/eps)),P_0)
                        P_1 = min(real(floor(P_1/eps)),P_1)
                        ! 
                        ! Save agent-specific 'bulk' daily entomological inoculation rate (EIR)
                        people(iagent)%health_status%malaria_status%EIR_att = lambda_1
                        !people(iagent)%health_status%malaria_status%EIR_att = P_1 ! Temporary check

                        ! Save agent-specific 'bulk' daily biting rate (hbr)
                        people(iagent)%health_status%malaria_status%hbr_att = lambda_all
                    !===
                    !
                    ! 2.2) SEIAR update -----------
                    !
                    if (stat == 1) then ! If susceptible (S) *****************************
                    !
                    !=== 
                        !
                        if ((generate_random() < P_1)) then    ! If infected by vector
                            !
                            ! Move to Exposed
                            people(iagent)%health_status%malaria_status%status=2
                            !
                            ! Intrinsic Incubation Period (IIP)
                            people(iagent)%health_status%malaria_status%infc_dur=iip
                            !
                        end if 
                        !
                    !===   
                    !
                    elseif (stat == 2) then ! If exposed (E) *****************************
                    !
                    !===
                        ! Check if IIP has finished
                        if (people(iagent)%health_status%malaria_status%infc_dur == 0) then
                            !
                            ! Update immunity level
                            people(iagent)%health_status%malaria_status%imm = min(people(iagent)%health_status%malaria_status%imm + dimmunity(people(iagent)%health_status%malaria_status%imm,e_0,e1,e2,A1), 1.)
                            !
                            ! Transition to symptomatic with probability prob_symp() if maternal immunity 
                            if ((generate_random() < prob_symp_sig(people(iagent)%health_status%malaria_status%imm,alph_max,age_alph_min(people(iagent)%agent_ID%age,alph_min,k_alph), &
                                                                                                                             age_i_star(people(iagent)%agent_ID%age,i_star_a,i_star_c,k_star),&
                                                                                                                             age_m_slope(people(iagent)%agent_ID%age,m_a,m_c,k_m))) & 
                                                    .and. (.not. people(iagent)%health_status%malaria_status%mat_im)) then 
                                !
                                people(iagent)%health_status%malaria_status%status=3
                                !
                                ! Update here Inew
                                !
                                ! Total new infections (j is the agent location, accessed before)
                                status_pointer(6)%arr_p_priv(j,ithread) = &
                                status_pointer(6)%arr_p_priv(j,ithread) + 1.
                                !
                                ! New infections broken down by age
                                Iage_stat_ptr(8,min(floor(people(iagent)%agent_ID%age+1),79))%arr_p_priv(j,ithread) = &
                                Iage_stat_ptr(8,min(floor(people(iagent)%agent_ID%age+1),79))%arr_p_priv(j,ithread) + 1.
                                ! Log-normally distributed times - function of imm
                                people(iagent)%health_status%malaria_status%infc_dur=tau_log(people(iagent)%health_status%malaria_status%imm,d_mu,mu_1,d_sig,sig_1)
                                !
                            else ! Otherwise asymptomatic 
                                people(iagent)%health_status%malaria_status%status=4

                                ! New chronic asymptomatic
                                if (generate_random() < fA_chr) then 
                               
                                    people(iagent)%health_status%malaria_status%infc_dur=tau_chr 
                                ! Otherwise log-normally distributed times - function of imm
                                else 
                                    !
                                    people(iagent)%health_status%malaria_status%infc_dur=tau_log(people(iagent)%health_status%malaria_status%imm,d_mu,mu_1,d_sig,sig_1)
                                    !
                                end if
                            end if
                            !
                        ! Otherwise reduce by 1 day the IIP counter
                        else 
                            !
                            people(iagent)%health_status%malaria_status%infc_dur=people(iagent)%health_status%malaria_status%infc_dur - 1
                            !
                        end if
                        !
                    !===  
                    !
                    elseif (stat == 3) then ! If infected symptomatic (I) *****************************
                    !
                    !===
                        !
                        ! Human to vector transmission
                        if ((generate_random() < P_0)) then    ! If infected by human
                            !
                            !$OMP ATOMIC
                            nbites(j) = nbites(j) + 1
                            !$END OMP ATOMIC
                            !
                        end if
                        !
                        ! Clearance of disease
                        if (people(iagent)%health_status%malaria_status%infc_dur == 0) then
                            people(iagent)%health_status%malaria_status%status=5
                        else 
                            people(iagent)%health_status%malaria_status%infc_dur=people(iagent)%health_status%malaria_status%infc_dur - 1
                        end if
                    !===                  
                    !
                    elseif (stat == 4) then ! If infected asymptomatic (A) *****************************
                    !
                    !===
                        !
                        ! Human to vector transmission
                        if ((generate_random() < P_0)) then    ! If infected by human
                            !
                            !$OMP ATOMIC
                            nbites(j) = nbites(j) + 1
                            !$END OMP ATOMIC
                            !
                        end if
                        !
                        ! Vector to human transmission 
                        if ((generate_random() < P_1)) then    ! If infected by vector
                            !
                            ! Move to Exposed
                            people(iagent)%health_status%malaria_status%status=2
                            !
                            ! Intrinsic Incubation Period (IIP)
                            people(iagent)%health_status%malaria_status%infc_dur=iip

                        !
                        ! Clearance of disease
                        elseif (people(iagent)%health_status%malaria_status%infc_dur == 0) then
                            people(iagent)%health_status%malaria_status%status=5
                        else 
                            people(iagent)%health_status%malaria_status%infc_dur=people(iagent)%health_status%malaria_status%infc_dur - 1
                        end if
                    !==    
                    !
                    elseif (stat == 5) then ! If recovered (R) *****************************
                    !
                    !===
                        ! Vector to human transmission 
                        if ((generate_random() < P_1)) then    ! If infected by vector
                            !
                            ! Move to Exposed
                            people(iagent)%health_status%malaria_status%status=2
                            !
                            ! Intrinsic Incubation Period (IIP)
                            people(iagent)%health_status%malaria_status%infc_dur=iip

                        !
                        ! Immunity loss
                        else
                            !
                            people(iagent)%health_status%malaria_status%imm = people(iagent)%health_status%malaria_status%imm*(1. - clearance_half(people(iagent)%agent_ID%age,d_c,d_a,k_e)*dt)
                            !
                            ! Transition to Susceptible
                            if (people(iagent)%health_status%malaria_status%imm < e_th) then 
                                !
                                people(iagent)%health_status%malaria_status%imm = 0.
                                people(iagent)%health_status%malaria_status%status=1
                                !
                            end if
                        end if 
                        !

                    !===    
                    !
                    end if
                    !
                    ! Base mortality
                    !===
                        !
                        if (.not. in_spinup) then
                        if (generate_random() <= mu_age(min(floor(people(iagent)%agent_ID%age),79))) then
                            !
                            people(iagent)%health_status%active_status%status=.false.
                            people(iagent)%health_status%malaria_status%EIR_att=0.
                            people(iagent)%health_status%malaria_status%hbr_att=0.
                            people(iagent)%health_status%malaria_status%imm=0.
                            ! Update this thread's column, not npeop(:) -- npeop(:) is
                            ! derived once/day in agents_post_diagnostics (mo_const.f90).
                            npeop_thread(j,ithread) = npeop_thread(j,ithread) - 1
                            !
                        end if
                        end if ! .not. in_spinup
                        !
                    !===
                else ! If agent is dead
                   !
                   ! nbirths_left(i,ithread) is this thread's own ticket pool for cell i
                   ! (set in agents_pre_diagnostics) -- no ATOMIC needed to claim from it.
                   claimed = nbirths_left(i,ithread)
                   nbirths_left(i,ithread) = nbirths_left(i,ithread) - 1
                   if (claimed > 0) then
                        !
                        people(iagent)%health_status%active_status%status=.true.  ! You are now alive,
                        people(iagent)%health_status%malaria_status%status=1      ! born susceptible
                        people(iagent)%agent_ID%age=0.                             ! and as a baby
                        people(iagent)%health_status%malaria_status%imm=0.        ! Immunity level is zero
                        people(iagent)%health_status%malaria_status%mat_im=.true. ! Maternal immunity is active
                        people(iagent)%agent_ID%w_NB=gengam(k_NB,k_NB)
                        !
                        if (generate_random() <= 0.51) then ! Sex
                            people(iagent)%agent_ID%sex=0   ! Female = 0
                        else
                            people(iagent)%agent_ID%sex=1   ! Male = 0
                        end if
                        ! Update this thread's column, not npeop(:) -- npeop(:) is
                        ! derived once/day in agents_post_diagnostics (mo_const.f90).
                        npeop_thread(i,ithread) = npeop_thread(i,ithread) + 1
                   end if
                end if ! If (active)
            end if ! If (mask_pop(currloc))
        !==
        !
        end subroutine agents_malaria
        !
        subroutine agents_dengue()


        end subroutine agents_dengue
        !
        !**************************************
        !============ Functions ===============
        !**************************************
        !
        function cumsum(a) result(r)
            ! https://fortran-lang.discourse.group/t/what-is-the-fastest-way-to-do-cumulative-sum-in-fortran-to-mimic-matlab-cumsum/1976/11
            !
            real, intent(in) :: a(:)
            real :: r(size(a))
            integer :: i
            !
            r(:) = [(sum(a(1:i)),i=1,size(a))]
            !
        end function cumsum
        !
        function find_face(r,cum_distr,sides) result(roll)
            ! r: uniformly distributed random number, [0,1)
            ! cum_distr: cumulative distribution (not normalized) of probabilities (the weights of each face of the dice)
            ! sides: number of dice sides
            implicit none
            !
            real, intent(in) :: r, cum_distr(sides)
            integer, intent(in) :: sides
            integer   :: roll
            !
            ! Local use only
            integer :: j
            roll = 0 
            !
            do j = 1, sides
                if (r <= cum_distr(j)) then
                    !
                    roll = j
                    !
                    exit
                end if 
            end do
            !
        end function find_face
        !
        function find_face0(r,cum_distr,sides) result(roll)
            ! r: uniformly distributed random number, [0,1)
            ! cum_distr: cumulative distribution (not normalized) of probabilities (the weights of each face of the dice)
            ! sides: number of dice sides
            implicit none
            !
            real, intent(in) :: r, cum_distr(sides)
            integer, intent(in) :: sides
            integer   :: roll
            !
            ! Local use only
            integer :: j
            roll = 0 
            !
            do j = 0, sides-1
                if (r <= cum_distr(j+1)) then
                    !
                    roll = j
                    !
                    exit
                end if 
            end do
            !
        end function find_face0
        !
        function find_masked_face(r,cum_distr,sides,mask_grav,mask_pop) result(roll)
            ! r: uniformly distributed random number, [0,1)
            ! cum_distr: cumulative distribution (not normalized) of probabilities (the weights of each face of the dice)
            ! sides: number of dice sides
            implicit none
            !
            real, intent(in) :: r, cum_distr(sides)
            logical, intent(in) :: mask_grav(sides)
            logical, intent(in) :: mask_pop(sides)
            integer, intent(in) :: sides
            integer             :: roll
            !
            ! Local use only
            integer :: j
            roll = 0
            !
            do j = 1, sides
                if (mask_grav(j) .and. mask_pop(j)) then ! Efficiency
                    !
                    if (r <= cum_distr(j)) then
                        !
                        roll = j
                        !
                        exit
                    end if 
                    !
                end if
            end do
            !
        end function find_masked_face

        function find_masked_face_2(r,cum_distr,sides,mask_pop) result(roll)
            ! r: uniformly distributed random number, [0,1)
            ! cum_distr: cumulative distribution (not normalized) of probabilities (the weights of each face of the dice)
            ! sides: number of dice sides
            implicit none
            !
            real, intent(in) :: r, cum_distr(sides)
            logical, intent(in) :: mask_pop(sides)
            integer, intent(in) :: sides
            integer             :: roll
            !
            ! Local use only
            integer :: j
            roll = 0
            !
            do j = 1, sides
                if (mask_pop(j)) then ! Efficiency
                    !
                    if (r <= cum_distr(j)) then
                        !
                        roll = j
                        !
                        exit
                    end if 
                    !
                end if
            end do
            !
        end function find_masked_face_2
        !
        function generate_random() result(rand_num)
        ! Wrap random number subroutine in a function to be able
        ! to use it inside an "if" statement

            implicit none
            real :: rand_num
            !
            call random_number(rand_num) ! Call the intrinsic subroutine
            !
        end function generate_random

        ! =============== Immunity functions =============================

        function dimmunity(imm,e_0,e1,e2,A1) result(delta_e)

        ! Return the acquired inmmunity after an infectious bite

        implicit none

        real, intent(in)  :: e_0     ! Maximum acquisition per infectious bite (when fully susceptible)
        real, intent(in)  :: imm     ! Current immunity level
        real, intent(in)  :: e1      ! Fast 
        real, intent(in)  :: e2      ! Slow
        real, intent(in)  :: A1      ! Coefficient
        real              :: delta_e ! Acquired immunity 

            delta_e = e_0*(A1*exp(-imm/e1) + (1-A1)*(exp(-imm/e2)))

        end function dimmunity

        function clearance_half(age,d_c,d_a,k_e) result(tau_a)

        ! Return half-life of waning immunity

        implicit none

        real, intent(in)  :: age     ! Agent age
        real, intent(in)  :: d_c     ! Clearance baseline for children
        real, intent(in)  :: d_a     ! Clearance baseline for adults
        real, intent(in)  :: k_e ! Maturation time scale (~15yrs)
        
        real :: tau_a                ! Half-life
            !
            tau_a = log(2.)/(d_c + (d_a - d_c) * (1-exp(-age/k_e)))

        end function clearance_half
        !
        function age_alph_min(age,alph_min,k) result(alph_min_age)

        ! Return minimum symptomatic probability as a function of age

        implicit none

        real, intent(in)  :: age        ! Agent age
        real, intent(in)  :: alph_min   ! 
        real, intent(in)  :: k          ! 
        
        real :: alph_min_age                ! 
            !
            alph_min_age  = alph_min*exp(-age/k)

        end function age_alph_min
        !
        function age_i_star(age,i_star_a,i_star_c,k_star) result(i_star_age)

        ! Return immunity level for I --> A transition as a function of age
        ! This is the inflection point in the sigmoidal curve

        implicit none

        real, intent(in)  :: age        ! Agent age
        real, intent(in)  :: i_star_a   ! Transition immunity level for adults
        real, intent(in)  :: i_star_c   ! Transition immunity level for children
        real, intent(in)  :: k_star     ! e-folding age to flip from children
                                        ! to adult
        
        real :: i_star_age              ! 
            !
            i_star_age  = i_star_a + (i_star_c - i_star_a)*exp(-age/k_star)

        end function age_i_star
        !
        function age_m_slope(age,m_a,m_c,k_m) result(m_slope_age)

        ! Return immunity level for I --> A transition as a function of age
        ! This is the inflection point in the sigmoidal curve

        implicit none

        real, intent(in)  :: age        ! Agent age
        real, intent(in)  :: m_a   ! Slope of sigmoid for adults
        real, intent(in)  :: m_c   ! Slope of sigmoid for children
        real, intent(in)  :: k_m   ! e-folding age to flip from children
                                   ! to adult
        
        real :: m_slope_age              ! 
            !
            m_slope_age  = m_a + (m_c - m_a)*exp(-age/k_m)

        end function age_m_slope
        !
        function prob_symp_sig(imm,alph_max,alph_min,e_m,sig_m) result(p)

        ! Return the acquired inmmunity after an infectious bite
        ! Sigmoidal function

        implicit none

        real, intent(in)  :: imm        ! Current immunity level
        real, intent(in)  :: e_m        ! inflection
        real, intent(in)  :: sig_m      ! "slope"
        real, intent(in)  :: alph_max   ! Maximum symptomatic fraction 
        real, intent(in)  :: alph_min   ! Minimum symptomatic fraction (1- maximum asymptomatic fraction) 

        real              :: p          ! Probability to be symptomatic

            p = alph_max*(1-1./(alph_max/(alph_max-alph_min)+exp(-sig_m*(imm-e_m))))

        end function prob_symp_sig
        !
        function prob_symp(imm,alph_min) result(p)

        ! Return the acquired inmmunity after an infectious bite
        ! Linear function

        implicit none

        real, intent(in)  :: imm        ! Current immunity level
        real, intent(in)  :: alph_min  ! Minimum symptomatic fraction (1- maximum asymptomatic fraction) 
        real              :: p          ! Probability to be symptomatic

            p = -(1-alph_min)*imm + 1

        end function prob_symp
        !
        function mean_normtimes(imm,d_mu,mu_1) result(mu_e)

        implicit none

        real, intent(in) :: imm 
        real, intent(in) :: d_mu, mu_1 
        real             :: mu_e

            mu_e = d_mu*imm + mu_1

        end function mean_normtimes
        !
        function sig_normtimes(imm,d_sig,sig_1) result(sig_e)

        implicit none

        real, intent(in) :: imm 
        real, intent(in) :: d_sig, sig_1 
        real             :: sig_e

            sig_e = d_sig*imm + sig_1

        end function sig_normtimes
        !
        function r4_normal_cd (c, d) result(r4_normal)

        !*****************************************************************************
        !
        ! This is a modified version of the function "R4_NORMAL_AB",
        ! which can be found at https://people.math.sc.edu/Burkardt/f_src/normal/normal.html
        ! 
        ! Author: John Burkardt
        ! Modified: 2013
        !
        !*****************************************************************************

          ! Returns a sample, r4_normal, of the normal probability distribution N(c,d)
          !
          ! Input, real - c:
          ! Input, real - d:

          implicit none
        
          real, intent(in) :: c
          real, intent(in) :: d
        
          ! Local use
          real :: r1
          real :: r2
          real :: x
          real :: r4_normal    !  Single precision (kind=4)
        
          r1 = generate_random()
          r2 = generate_random()
          x = sqrt ( - 2.0E+00 * log ( r1 ) ) * cos ( 2.0E+00 * pi * r2 )

            r4_normal = c + d * x     ! Transform from N(0,1) to N(c,d)

          end function r4_normal_cd

          ! ** Not in use **
          function mean_log_to_norm(a,b) result(c) 
          !
          ! Returns mean, c, of normal distribution N(c,d) from log-normal distribution logN(a,b)
          !
          ! Input, real -  a: Mean of the log-normal PDF
          ! Input, real -  b: Standard deviation of the log-normal PDF
          !
          ! Output, real - c: Mean of the corresponding normal distribution

          implicit none  

          real, intent(in) :: a, b 
          real :: c

            c = log(a) - 0.5*b**2

          end function mean_log_to_norm
          !
          ! ** Not in use **
          function std_log_to_norm(a,b) result(d)
          !
          ! Returns standard deviation (std), d, of normal distribution N(c,d) from log-normal distribution logN(a,b)
          !
          ! Input, real -  a: Mean of the log-normal PDF
          ! Input, real -  b: Standard deviation of the log-normal PDF
          !
          ! Output, real - d: Mean of the corresponding normal distribution

          implicit none  

          real, intent(in) :: a, b 
          real :: d

            d = sqrt(log(1 + (b/a)**2))

          end function std_log_to_norm
          !
          function tau_log(imm,d_mu,mu_1,d_sig,sig_1) result(tau)
          !
          ! Returns log-normally distributed clearance time, tau ~ logN(a,b), given an immunity level imm
          !
          ! ------------ Uses ------------------- -------------- Gets ---------------
          !     mean_logtimes(imm,d_mu,mu_1) --> | a: Mean logNorm PDF               |
          !     sig_logtimes(imm,d_sig,sig_1)--> | b: STD  logNorm PDF               |
          !     mean_log_to_norm(a,b)        --> | c: Mean    Norm PDF               |
          !     std_log_to_norm(a,b)         --> | d: STD     Norm PDF               |
          !     r4_normal_cd(c,d)            --> | N(c,d): Normally distr. Rand. Num.|
          !--------------------------------------------------------------------------
          !     tau ~ exp(N(c,d))
          !
          implicit none
          ! 
          ! Result
          integer :: tau
          !
          ! Input
          real, intent(in) :: imm
          real, intent(in) :: d_mu, mu_1, d_sig, sig_1
          !
          ! Local use
          real :: c,d
          !real :: a,b

          ! The reported mean and std are those of the corresponding normal distribution.
          !a = mean_logtimes(imm,d_mu,mu_1)
          !b = sig_logtimes(imm,d_sig,sig_1)

          c = mean_normtimes(imm,d_mu,mu_1)
          d = sig_normtimes(imm,d_sig,sig_1)

          !c = mean_log_to_norm(a,b)
          !d = std_log_to_norm(a,b)

          tau = ceiling(exp(r4_normal_cd(c,d)))

          end function tau_log

end MODULE mo_agents