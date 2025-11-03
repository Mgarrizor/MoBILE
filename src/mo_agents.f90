MODULE mo_agents
! This module contains methods on agents
!
! 
! Adrian M. Tompkins 2014 
! tompkins@ictp.it

! Miguel Garrido Zornoza 2024
! mgarrizoraca@gmail.com

USE mo_const
USE mo_control

USE omp_lib

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
        real    :: e_l      ! Endemicity level [0,1]
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
        integer :: age     ! 0-X
        integer :: sex     ! F/M   [Non-functional]
        integer :: wealth  ! L/M/H [Non-functional]
        real    :: ratio   ! Human to agent ratio of the agent
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

        subroutine agents_init(nxy,idis,nagent,npeop,n_attempt,mask_pop,pop_dens,scale,A_cell)
            ! 
            ! 
            !
            implicit none
            !
            integer, intent(in) :: idis ! 0 = Cholera: SIAR  ; 1 = Malaria: SEIR [Non-functional]
            integer, intent(in) :: nxy                          !
            integer, intent(in) :: nagent                       !
            integer, allocatable, intent(inout) :: npeop(:)     !
            integer, allocatable, intent(out) :: n_attempt(:)   !
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
            real :: norm, norm_check, rand
            integer :: nfaces
            integer :: j          ! Short trip location index
            real, allocatable :: cdf_health(:) ! Cumulative distribution to asign agent health based on initial profile
            real :: cdf(nxy)      ! Cumulative distribution to asign agent location based on human density
            integer :: stat_health
            
            !
            call random_seed()       ! Each simulation generates a different series of random numbers

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
            print *, 'Standard human to agent ratio ~', P_a
            !
            ! Initialize array of types "agent"
            allocate(people(nagent))
            ! Allocate array of the number of agents in each grid cell
            allocate(npeop(nxy))
            ! Allocate array of the human to agent ratio
            allocate(HA(nxy))
            ! Allocate array of number of growth attempts 
            allocate(n_attempt(nxy))
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
                            people(indx)%agent_ID%age=find_face0(generate_random(),age_weights(:),size(age_weights(:)))
                            age_counts(people(indx)%agent_ID%age) = age_counts(people(indx)%agent_ID%age) + 1
                            people(indx)%agent_ID%name=indx     !
                            people(indx)%agent_ID%sex=0         ! F = 0, M = 1 [Not in use]
                            people(indx)%agent_ID%wealth=0      ! L = 0, M = 1, H = 2 [Not in use]

                            ! Initialize health attributes
                            if (random .and. (.not. rand_seed)) then

                                call random_number(rand)
                                stat_health = find_face(rand,cdf_health(:),nfaces)
                                !
                                if (idis == 1) then
                                    !  
                                    people(indx)%health_status%malaria_status%e_l = 0.5
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
                                        ! Log-normally distributed times - function of e_l
                                        people(indx)%health_status%malaria_status%infc_dur=tau_log(people(indx)%health_status%malaria_status%e_l,d_mu,mu_1,d_sig,sig_1)
                                        !
                                    else if (stat_health == 4) then !(Asymptomatic)
                                        !
                                        ! Chronic asymptomatics
                                        if (generate_random() < fA_chr) then 
                                             !
                                             people(indx)%health_status%malaria_status%infc_dur=tau_chr
                                             !
                                        else 
                                             ! Log-normally distributed times - function of e_l
                                             people(indx)%health_status%malaria_status%infc_dur=tau_log(people(indx)%health_status%malaria_status%e_l,d_mu,mu_1,d_sig,sig_1)
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
                                if (idis == 1) then  ! For malaria we generate a low percentage of chronic asymptomatics (1%)
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
            norm_check = sum(max(pop_dens(:)*A_cell(:)-npeop(:), 0.)) ! Weighted by cell area
            cdf(:) = cumsum(max(pop_dens(:)*A_cell(:)-npeop(:), 0.))/norm_check
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
            print *, indx, nagent, cdf(nxy)
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
                   people(indx)%agent_ID%age=find_face0(generate_random(),age_weights(:),size(age_weights(:)))
                   age_counts(people(indx)%agent_ID%age) = age_counts(people(indx)%agent_ID%age) + 1
                   people(indx)%agent_ID%name=indx     !
                   people(indx)%agent_ID%sex=0         ! F = 0, M = 1
                   people(indx)%agent_ID%wealth=0      ! L = 0, M = 1, H = 2
                   !
                   ! Initialize health attributes
                   if (random .and. (.not. rand_seed)) then
                       call random_number(rand)
                       stat_health = find_face(rand,cdf_health(:),nfaces)
                       !
                       if (idis == 1) then
                           !  
                           !  
                           people(indx)%health_status%malaria_status%e_l = 0.5
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
                               ! Log-normally distributed times - function of e_l
                               people(indx)%health_status%malaria_status%infc_dur=tau_log(people(indx)%health_status%malaria_status%e_l,d_mu,mu_1,d_sig,sig_1)
                               !
                           else if (stat_health == 4) then !(Symptomatic)
                               !
                               ! Chronic asymptomatics
                               if (generate_random() < fA_chr) then 
                                    !
                                    people(indx)%health_status%malaria_status%infc_dur=tau_chr
                                    !
                               else 
                                    ! Log-normally distributed times - function of e_l
                                    people(indx)%health_status%malaria_status%infc_dur=tau_log(people(indx)%health_status%malaria_status%e_l,d_mu,mu_1,d_sig,sig_1)
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
                   indx = indx + 1
               end if
               !
            end do
            !
            HA(:) = pop_dens(:)*A_cell(:)/npeop(:) ! Assign human to agent ratio once all agents have been initialised
            !
            write(*,*) ' '
            print *, 'Check normalization of agents', sum(npeop(:)/pop_dens(:)*scale(:), mask=((pop_dens(:) > 0.) .and. (npeop(:) > 0))) & 
                                                              /sum(merge(1, 0, mask_pop(:)), mask=((pop_dens(:) > 0.) .and. (npeop(:) > 0))), '~ 1?'
            !
            print '("Initialized:", I8, A8)', nagent, '  agents'
            !
            !deallocate(A_cell)
        end subroutine agents_init

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
            allocate(Iage_stat_ptr(5,num_elements))
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

        subroutine agents_diagnostics(idis,scale)
        !===
            ! Calculate bulk statistics to feed into the disease source integration
            !
            integer, intent(in) :: idis ! 0 = Cholera: SIAR  ; 1 = Malaria: SEIAR ; 2 = Dengue [Non-functional]
            real, allocatable, intent(in)    :: scale(:)
            !integer, intent(out):: counter ! Number of alive agents
            !
            ! Local use only
            integer :: iagent, istat, iloc, iage, j
            logical :: iactive

            SELECT case(idis)
            case (0) ! Cholera -------------------------------
            !
            S(:) = 0.
            I(:) = 0.
            A(:) = 0.
            R(:) = 0.
            do iagent = 1,nagent
                !
                istat    =  people(iagent)%health_status%cholera_status%status
                iactive  =  people(iagent)%health_status%active_status%status
                iloc     =  people(iagent)%location_status%currloc
                !
                ! Pointer approach to allow vectorization (discarded old branching if ... elseif ...)
                if (iactive) then
                    status_pointer(istat)%arr_p(iloc) = &
                    status_pointer(istat)%arr_p(iloc) + 1.
                end if
                !
            end do 
            !
            S(:) = scale(:)*S(:)
            I(:) = scale(:)*I(:)
            A(:) = scale(:)*A(:)
            R(:) = scale(:)*R(:)
            !=================================================

            !
            case (1) ! Malaria -------------------------------
            !
            S(:) = 0.
            E(:) = 0.
            I(:) = 0.
            A(:) = 0.
            R(:) = 0.
            !
            EIR(:) = 0.
            imm(:) = 0.
            hbr(:) = 0.
            !
            if (diag_age) then
                Sa(:,:) = 0.
                Ea(:,:) = 0.
                Ia(:,:) = 0.
                Aa(:,:) = 0.
                Ra(:,:) = 0.
            end if 
            !
            do iagent = 1,nagent
                !
                istat   =  people(iagent)%health_status%malaria_status%status
                iactive =  people(iagent)%health_status%active_status%status
                iloc    =  people(iagent)%location_status%currloc
                iage    =  min(people(iagent)%agent_ID%age,79)
                !
                ! Pointer approach to allow vectorization (discarded old branching if ... elseif ...)
                if (iactive) then
                    ! bulk
                    status_pointer(istat)%arr_p(iloc) = &
                    status_pointer(istat)%arr_p(iloc) + 1.
                    !
                    if (diag_age) then
                        ! Disaggregated by age
                        Iage_stat_ptr(istat,iage+1)%arr_p(iloc) = &
                        Iage_stat_ptr(istat,iage+1)%arr_p(iloc) + 1.
                        !
                    end if
                end if
                !
                EIR(iloc) = EIR(iloc) + people(iagent)%health_status%malaria_status%EIR_att
                imm(iloc) = imm(iloc) + people(iagent)%health_status%malaria_status%e_l
                hbr(iloc) = hbr(iloc) + people(iagent)%health_status%malaria_status%hbr_att
                !
            end do 
            !
            S(:) = HA(:)*S(:)/A_cell(:)
            E(:) = HA(:)*E(:)/A_cell(:)
            I(:) = HA(:)*I(:)/A_cell(:)
            A(:) = HA(:)*A(:)/A_cell(:)
            R(:) = HA(:)*R(:)/A_cell(:)
            !
            if (diag_age) then
                do j = 1, size(age_blocks(:))
                    Ia(:,j) = HA(:)*Ia(:,j)/A_cell(:)
                    Aa(:,j) = HA(:)*Aa(:,j)/A_cell(:)
                end do
            end if
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
        end subroutine agents_diagnostics

        subroutine agents_update(idis,iagent,itime,n_attempt,npeop,nbites,m_0,m_1,m_all)
        !===
            ! This subroutine updates agent disease and mobility statuses (mobility non-functional - to be implemented if Marie-Curie is funded)
            implicit none

            real, allocatable, intent(in) :: m_0(:)  ! Susceptible vector to host ratio times the vector biting rate
            real, allocatable, intent(in) :: m_1(:)  ! Infective   vector to host ratio times the vector biting rate
            real, allocatable, intent(in) :: m_all(:)  ! Vector to host ratio times the vector biting rate
            
            integer, intent(in) :: idis              ! Disease ID (0: Cholera, 1: Malaria)
            integer, intent(in) :: iagent            ! Agent ID (integer number)
            integer, intent(in) :: itime             ! Current time step
            integer, allocatable, intent(inout) :: n_attempt(:)   ! (nxy) Number of growth attempts at location of iagent at time itime
            integer, allocatable, intent(inout) :: npeop(:)       ! (nxy) Number of agents in each grid cell 
            integer, allocatable, intent(inout) :: nbites(:)      ! (nxy) Infective bites (vectors that were infected upon bitting a human)

            ! *************** Start subroutine *******************
            ! 
            SELECT case(idis)
            case (0) ! Cholera
            !
            call agents_cholera(iagent,itime,n_attempt)
            !
            case (1) ! Malaria
            ! 
            call agents_malaria(iagent,n_attempt,npeop,nbites,m_0,m_1,m_all) 
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
        subroutine agents_cholera(iagent,itime,n_attempt)

            implicit none
            integer, intent(in) :: iagent            ! Agent ID (integer number)
            integer, intent(in) :: itime             ! Time step
            integer, allocatable, intent(inout) :: n_attempt(:)   ! (nxy) Number of growth attempts at location of iagent at time itime

            ! Local use only
            real :: rand    ! Uniformly distributed random number to throw dices
            integer :: stat ! Agent health status
            integer :: i    ! Agent location
            integer :: j    ! Location where agent moves
            logical :: active ! Is the agent alive?
            logical :: cyc    ! Cycle flag for growth event

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
                        if (generate_random() <= mu) then ! Death
                            !
                            people(iagent)%health_status%active_status%status=.false.
                            npeop(i) = npeop(i) - 1
                            !
                        end if
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
                        if (generate_random() <= mu) then ! Death
                            !
                            people(iagent)%health_status%active_status%status=.false.
                            npeop(i) = npeop(i) - 1
                            !
                        end if
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
                        if (generate_random() <= mu) then ! Death
                            !
                            people(iagent)%health_status%active_status%status=.false.
                            npeop(i) = npeop(i) - 1
                            !
                        end if
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
                        if (generate_random() <= mu) then 
                            !
                            people(iagent)%health_status%active_status%status=.false.
                            npeop(i) = npeop(i) - 1
                            !
                        end if
                        !
                    end if 
                else ! If agent is dead
                   !
                   ! We try to activate agent "iagent" a maximum number of (npeop(i) - nattempt(i)) times
                   ! If successful then cycle (cyc=.true.) to next agent
                   cyc=.false.
                   do while ((n_attempt(i) .le. npeop(i)) .and. (.not. cyc))
                        if (generate_random() <= mu) then ! Growth event
                             !
                             people(iagent)%health_status%active_status%status=.true. ! You are now alive,
                             people(iagent)%health_status%cholera_status%status=1     ! born susceptible
                             people(iagent)%agent_ID%age=0                            ! and as a baby
                             !
                             if (generate_random() <= 0.51) then ! Sex
                                 people(iagent)%agent_ID%sex=0   ! Female = 0
                             else  
                                 people(iagent)%agent_ID%sex=1   ! Male = 1
                             end if
                             cyc=.true.
                             n_attempt(i) = n_attempt(i) + 1
                             npeop(i) = npeop(i) + 1
                        else
                             n_attempt(i) = n_attempt(i) + 1
                        end if 
                    end do
                end if ! If (active)
            end if ! If (mask_pop(currloc))
        !==
        end subroutine agents_cholera
        !
        !
        subroutine agents_malaria(iagent,n_attempt,npeop,nbites,m_0,m_1,m_all)

            implicit none
            integer, intent(in) :: iagent            ! Agent ID (integer number)
            integer, allocatable, intent(inout) :: n_attempt(:)   ! (nxy) Number of growth attempts at location of iagent at time itime
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
            logical :: active ! Is the agent alive?
            logical :: cyc    ! Cycle flag for growth event

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

                                ! Update number of agents in either grid cell
                                !$OMP ATOMIC
                                npeop(i) = npeop(i) - 1 
                                npeop(j) = npeop(j) + 1
                                !$END OMP ATOMIC
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

                                ! Update number of agents in either grid cell
                                !$OMP ATOMIC
                                npeop(i) = npeop(i) - 1 
                                npeop(j) = npeop(j) + 1
                                !$END OMP ATOMIC
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
                    if (people(iagent)%health_status%malaria_status%mat_im) then ! If maternal immunity is active
                        if (generate_random() < mat_rate) then                   ! becomes inactive with a probability (mat_rate)
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
                        P_0 = P_max*(1 - exp(-lambda_0*P_h0))
                        !
                        ! Vector to Human transmission
                        !
                        lambda_1 = m_1(j)*1. ! f(a,t) = 1 
                        P_1 = 1 - exp(-lambda_1*P_v0)
                        !
                        ! Apply numerical threshold ---> Need to optimize transmission events for cases where P < epsilon
                        P_0 = min(real(floor(P_0/eps)),P_0)
                        P_1 = min(real(floor(P_1/eps)),P_1)
                        ! 
                        ! Save agent-specific daily entomological inoculation rate
                        people(iagent)%health_status%malaria_status%EIR_att = lambda_1

                        ! Save agent-specific biting rate (hbr)
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
                            ! Update immunity/endemicity level
                            people(iagent)%health_status%malaria_status%e_l = people(iagent)%health_status%malaria_status%e_l + endemicity(people(iagent)%health_status%malaria_status%e_l,e_0,e1,e2,A1)
                            !
                            ! Transition to symptomatic with probability prob_symp() if maternal immunity 
                            if ((generate_random() < prob_symp_sig(people(iagent)%health_status%malaria_status%e_l,alph_max,alph_min,e_m,sig_m)) .and. (.not. people(iagent)%health_status%malaria_status%mat_im)) then 
                                !
                                people(iagent)%health_status%malaria_status%status=3
                                !
                                ! Log-normally distributed times - function of e_l
                                people(iagent)%health_status%malaria_status%infc_dur=tau_log(people(iagent)%health_status%malaria_status%e_l,d_mu,mu_1,d_sig,sig_1)
                                !
                            else ! Otherwise asymptomatic 
                                people(iagent)%health_status%malaria_status%status=4

                                ! New chronic asymptomatic
                                if (generate_random() < fA_chr) then 
                               
                                    people(iagent)%health_status%malaria_status%infc_dur=tau_chr 
                                ! Otherwise log-normally distributed times - function of e_l
                                else 
                                    !
                                    people(iagent)%health_status%malaria_status%infc_dur=tau_log(people(iagent)%health_status%malaria_status%e_l,d_mu,mu_1,d_sig,sig_1)
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
                            people(iagent)%health_status%malaria_status%e_l = people(iagent)%health_status%malaria_status%e_l*(1. - rho*dt)
                            !
                            ! Transition to Susceptible
                            if (people(iagent)%health_status%malaria_status%e_l < e_th) then 
                                !
                                people(iagent)%health_status%malaria_status%e_l = 0.
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
                        if (generate_random() <= mu) then 
                            !
                            people(iagent)%health_status%active_status%status=.false.
                            people(iagent)%health_status%malaria_status%EIR_att=0.
                            people(iagent)%health_status%malaria_status%hbr_att=0.
                            people(iagent)%health_status%malaria_status%e_l=0.
                            !$OMP ATOMIC
                            npeop(j) = npeop(j) - 1
                            !$END OMP ATOMIC
                            !
                        end if
                        !
                    !===
                else ! If agent is dead
                   !
                   ! We try to activate agent "iagent" a maximum number of (npeop(i) - nattempt(i)) times
                   ! If successful then cycle (cyc=.true.) to next agent
                   cyc=.false.
                   do while ((n_attempt(i) .le. npeop(i)) .and. (.not. cyc))
                        if (generate_random() <= mu) then ! Growth event
                             !
                             people(iagent)%health_status%active_status%status=.true.  ! You are now alive,
                             people(iagent)%health_status%malaria_status%status=1      ! born susceptible
                             people(iagent)%agent_ID%age=0                             ! and as a baby
                             people(iagent)%health_status%malaria_status%e_l=0.        ! Endemicity level is zero
                             people(iagent)%health_status%malaria_status%mat_im=.true. ! Maternal immunity is active
                             !
                             if (generate_random() <= 0.51) then ! Sex
                                 people(iagent)%agent_ID%sex=0   ! Female = 0
                             else 
                                 people(iagent)%agent_ID%sex=1   ! Male = 0
                             end if
                             cyc=.true.
                             !$OMP ATOMIC
                             n_attempt(i) = n_attempt(i) + 1
                             npeop(i) = npeop(i) + 1
                             !$END OMP ATOMIC
                        else
                             !$OMP ATOMIC
                             n_attempt(i) = n_attempt(i) + 1
                             !$END OMP ATOMIC
                        end if 
                    end do
                end if ! If (active)
            end if ! If (mask_pop(currloc))
        !==
        !
        end subroutine agents_malaria
        !
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

        function endemicity(e_l,e_0,e1,e2,A1) result(delta_e)

        ! Return the acquired inmmunity after an infectious bite

        implicit none

        real, intent(in)  :: e_0     ! Maximum acquisition per infectious bite (when fully susceptible)
        real, intent(in)  :: e_l     ! Current immunity level
        real, intent(in)  :: e1      ! Fast 
        real, intent(in)  :: e2      ! Slow
        real, intent(in)  :: A1      ! Coefficient
        real              :: delta_e ! Acquired immunity 

            delta_e = e_0*(A1*exp(-e_l/e1) + (1-A1)*(1-e_l/e2))

        end function endemicity
        !
        function prob_symp_sig(e_l,alph_max,alph_min,e_m,sig_m) result(p)

        ! Return the acquired inmmunity after an infectious bite
        ! Sigmoidal function

        implicit none

        real, intent(in)  :: e_l        ! Current immunity level
        real, intent(in)  :: e_m        ! inflection
        real, intent(in)  :: sig_m      ! "slope"
        real, intent(in)  :: alph_max   ! Maximum symptomatic fraction 
        real, intent(in)  :: alph_min   ! Minimum symptomatic fraction (1- maximum asymptomatic fraction) 

        real              :: p          ! Probability to be symptomatic

            p = alph_max*(1-1./(alph_max/(alph_max-alph_min)+exp(-sig_m*(e_l-e_m))))

        end function prob_symp_sig
        !
        function prob_symp(e_l,alph_min) result(p)

        ! Return the acquired inmmunity after an infectious bite
        ! Linear function

        implicit none

        real, intent(in)  :: e_l        ! Current immunity level
        real, intent(in)  :: alph_min  ! Minimum symptomatic fraction (1- maximum asymptomatic fraction) 
        real              :: p          ! Probability to be symptomatic

            p = -(1-alph_min)*e_l + 1

        end function prob_symp
        !
        function mean_normtimes(e_l,d_mu,mu_1) result(mu_e)

        implicit none

        real, intent(in) :: e_l 
        real, intent(in) :: d_mu, mu_1 
        real             :: mu_e

            mu_e = d_mu*e_l + mu_1

        end function mean_normtimes
        !
        function sig_normtimes(e_l,d_sig,sig_1) result(sig_e)

        implicit none

        real, intent(in) :: e_l 
        real, intent(in) :: d_sig, sig_1 
        real             :: sig_e

            sig_e = d_sig*e_l + sig_1

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
          function tau_log(e_l,d_mu,mu_1,d_sig,sig_1) result(tau)
          !
          ! Returns log-normally distributed clearance time, tau ~ logN(a,b), given an immunity level e_l
          !
          ! ------------ Uses ------------------- -------------- Gets ---------------
          !     mean_logtimes(e_l,d_mu,mu_1) --> | a: Mean logNorm PDF               |
          !     sig_logtimes(e_l,d_sig,sig_1)--> | b: STD  logNorm PDF               |
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
          real, intent(in) :: e_l
          real, intent(in) :: d_mu, mu_1, d_sig, sig_1
          !
          ! Local use
          real :: c,d
          !real :: a,b

          ! The reported mean and std are those of the corresponding normal distribution.
          !a = mean_logtimes(e_l,d_mu,mu_1)
          !b = sig_logtimes(e_l,d_sig,sig_1)

          c = mean_normtimes(e_l,d_mu,mu_1)
          d = sig_normtimes(e_l,d_sig,sig_1)

          !c = mean_log_to_norm(a,b)
          !d = std_log_to_norm(a,b)

          tau = ceiling(exp(r4_normal_cd(c,d)))

          end function tau_log

end MODULE mo_agents