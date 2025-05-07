MODULE mo_agents
! This module contains methods on agents
!
! Slightly modified from 
! Adrian M. Tompkins 2014 
! tompkins@ictp.it

! Miguel Garrido Zornoza 2024
! mgarrizoraca@gmail.com

USE mo_const
USE mo_control
!
    implicit none

    ! Variable declarations

    ! Type declarations

    type cholera
        integer :: status ! S=1, I=2, A=3, R=4
    end type cholera

    type malaria
        integer :: status ! S=1, E= 2, I=3, R=4
    end type malaria

    type active
        logical :: status ! .false.= Dead ; .true.= Alive
    end type active

    type health
        type(active)  :: active_status
        type(cholera) :: cholera_status
        type(malaria) :: malaria_status

    end type health

    type location
        integer :: homeloc ! xy Default/"home" location
        integer :: currloc ! xy Current location
        integer :: shortloc! xy Fast/short trip location (for now 1)
        !integer :: longloc ! xy Long trip location [Non-functional]
    end type location

    type agentID
        integer :: name    ! The name of the agent is an integer
        integer :: age     ! 0-X   [Non-functional]
        integer :: sex     ! F/M   [Non-functional]
        integer :: wealth  ! L/M/H [Non-functional]
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

        subroutine agents_init(nxy,idis,nagent,npeop,n_attempt,mask_pop,pop_dens,scale,dist)
            ! 
            ! For now, assume normally distributed population (need mean and std as input
            ! but for now hardcoded). In the future we could hardcode a set of basic distributions.
            ! To Do - Initialize agents based on input distributions.
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

            real, allocatable, intent(in)   :: dist(:,:)     ! Distance matrix

            real, intent(out) :: scale ! Scale factor to translate number of excretion events into density

            !
            !
            ! Local use only
            integer :: ixy ! Looping long index
            integer :: ipeo, indx, loc
            real :: norm, rand
            integer :: j          ! Short trip location index
            real :: cdf_health(4) ! Cumulative distribution to asign agent health based on initial profile
            real :: cdf(nxy)      ! Cumulative distribution to asign agent location based on human density
            integer :: stat_health
            real :: band = 0.10
            !
            call random_seed()       ! Each simulation generates a different series of random numbers

            ! Calculate number of agents per grid cell for a given total, nagent, and
            ! the input human population density, pop_dens
            !
            ! When all agents are active they represent the (1+band)*100 % of
            ! the steady-state population density
            norm = sum(pop_dens(:)*(1.+ band)) ! Valid for regular grid (otherwise should be weighted by cell area)
            !
            scale = norm/nagent
            !
            ! Initialize array of types "agent"
            allocate(people(nagent))
            ! Allocate array with the number of agents in each grid cell
            allocate(npeop(nxy))
            ! Allocate array of number of growth attempts 
            allocate(n_attempt(nxy))
            !
            ! CDF for initial health status
            if (random) then
                ! To Do: We should here use disID input to build a disease-dependent dice
                cdf_health(:) = cumsum([0.25,0.25,0.25,0.25])/sum([0.25,0.25,0.25,0.25])
                !
            else ! Follow initial condition profile
                
            end if
            !
            ! Need an index to keep track of agents
            indx = 1
            do ixy = 1,nxy
                write(*,'(1a1,A19,F6.1,A2)', advance='no') char(13),'Initializing agents',(real(ixy)/real(nxy)*100.),' %'
                if ((mask_pop(ixy))) then ! If area is populated or not missing (FillValue)
                    !
                    ! Calculate number of agents in ixy as the fraction of the total pop at ixy times the total number of agents
                    ! We start below the steady-state and fill it up to max.
                    ! When
                    npeop(ixy) = floor(pop_dens(ixy)*(1.+ band)/norm*nagent) ! Rounding error is big, we correct at the end
                    !
                    if (npeop(ixy) /= 0) then ! If there is someone
                        do ipeo = 1,npeop(ixy)
                            !
                            ! Initialize main agent attributes
                            people(indx)%agent_ID%age=20        ! Fixed for now. To Do: pick based on distribution
                            people(indx)%agent_ID%name=indx     !
                            people(indx)%agent_ID%sex=0         ! F = 0, M = 1 [Not in use]
                            people(indx)%agent_ID%wealth=0      ! L = 0, M = 1, H = 2 [Not in use]

                            ! Initialize health attributes
                            if (random .and. (.not. rand_seed)) then
                                !
                                call random_number(rand)
                                stat_health = find_face(rand,cdf_health(:),4)
                                !
                            else 
                                !
                                stat_health = 1
                                !
                            end if
                            people(indx)%health_status%cholera_status%status=stat_health !(S:1, I:2, A:3, R:4)
                            people(indx)%health_status%malaria_status%status=stat_health !(S:1, E:2, I:3, R:4)

                            people(indx)%health_status%active_status%status=.true.       ! All agents are initially alive

                            ! Initialize location attributes
                            people(indx)%location_status%homeloc=ixy
                            people(indx)%location_status%currloc=ixy
                            !
                            call random_number(rand) ! Asign visiting location based on mobility scheme
                            j = find_masked_face(ixy,rand,Q_cum(:,ixy),nxy,mask_grav(:,ixy),mask_pop(:)) ! If agent is mobile j /= 0
                            !
                            people(indx)%location_status%shortloc=j
                            !
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
            ! For this, build a biased dice (see functions below) with weights 
            ! prop. to pop_dens(:) and throw it.
            cdf(:) = cumsum(pop_dens(:)*(1.+ band))/norm
            !
            !
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
                   people(indx)%agent_ID%age=20        ! Fixed for now. To Do: pick based on distribution
                   people(indx)%agent_ID%name=indx     !
                   people(indx)%agent_ID%sex=0         ! F = 0, M = 1
                   people(indx)%agent_ID%wealth=0      ! L = 0, M = 1, H = 2
                   !
                   ! Initialize health attributes
                   if (random .and. (.not. rand_seed)) then
                       call random_number(rand)
                       stat_health = find_face(rand,cdf_health(:),4)
                   else 
                       stat_health = 1
                   end if
                   people(indx)%health_status%cholera_status%status=stat_health !(Susceptible)
                   people(indx)%health_status%malaria_status%status=stat_health !(Susceptible)
                   !
                   people(indx)%health_status%active_status%status=.true.       ! All agents are initially alive
                   !
                   ! Initialize location attributes (for now only home is functional)
                   people(indx)%location_status%homeloc=loc
                   people(indx)%location_status%currloc=loc
                   !
                   j = find_masked_face(loc,rand,Q_cum(:,loc),nxy,mask_grav(:,loc),mask_pop(:)) ! If agent is mobile j /= 0
                   !
                   people(indx)%location_status%shortloc=j   
                   !
                   indx = indx + 1
               end if
               !
            end do
            !
            ! Note: npeop(:) is now the total number of agents.
            ! If all agents are active they represent (1+band)*100% of the steady-state
            ! population density. We now factor it back to get the number of
            ! alive agents that would represent the 100% of the steady-state.
            ! This number is then used in the "agents_update" subroutine.
            !
            npeop(:) = floor((1./(1.+band))*npeop(:))
            write(*,*) ' '
            !
        end subroutine agents_init

        subroutine agents_diagnostics(idis,scale,counter)
            ! Calculate bulk statistics to feed into the disease source integration
            !
            integer, intent(in) :: idis ! 0 = Cholera: SIAR  ; 1 = Malaria: SEIR [Non-functional]
            real, intent(in)    :: scale
            integer, intent(out):: counter ! Number of alive agents
            !
            ! Local use only
            integer :: iagent, stat
            logical :: active
    
            !
            counter = 0

            SELECT case(idis)
            case (0) ! Cholera
            !
            S(:) = 0.
            I(:) = 0.
            A(:) = 0.
            R(:) = 0.
            do iagent = 1,nagent
                stat =  people(iagent)%health_status%cholera_status%status
                active  =  people(iagent)%health_status%active_status%status
                if (stat == 1 .and. active) then
                    S(people(iagent)%location_status%currloc) = S(people(iagent)%location_status%currloc) + 1.
                elseif (stat == 2 .and. active) then
                    I(people(iagent)%location_status%currloc) = I(people(iagent)%location_status%currloc) + 1.
                elseif (stat == 3 .and. active) then
                    A(people(iagent)%location_status%currloc) = A(people(iagent)%location_status%currloc) + 1.
                elseif (stat == 4 .and. active) then
                    R(people(iagent)%location_status%currloc) = R(people(iagent)%location_status%currloc) + 1.
                end if 

                if (active) then
                    counter = counter + 1
                end if

            end do 
            S(:) = scale*S(:)
            I(:) = scale*I(:)
            A(:) = scale*A(:)
            R(:) = scale*R(:)

            !
            case (1) ! Malaria [Non-functional]
            !
            case default
                print *, "Incorrect case, choose disID between: 0 (cholera)"
                STOP
            end SELECT

            !

        end subroutine agents_diagnostics

        subroutine agents_update(idis,iagent,itime,n_attempt)
            ! This subroutine takes one time step with agent method
            implicit none
            integer, intent(in) :: idis, iagent            ! Disease ID (0: Cholera) and Agent ID (integer number)
            integer, intent(in) :: itime                   ! Time step
            integer, intent(inout) :: n_attempt(:)         ! (nxy) Number of growth attempts at location of iagent at time itime

            ! Local use only
            real :: rand    ! Uniformly distributed random number to throw dices
            integer :: stat ! Agent health status
            integer :: i    ! Agent location
            integer :: j    ! Location where agent moves
            logical :: active ! Is the agent alive?
            logical :: cyc    ! Cycle flag for growth event


            ! "Implicit" input (from mo_const):

            ! logical, allocatable, intent(in) :: mask_pop(:) !
            ! logical, allocatable, intent(in) :: mask_mob(:) !
            ! 
            ! Cholera =================================
            !
            ! real, allocatable, intent(in) :: B(:)    ! Bacterial load for infection probability
            ! real, allocatable, intent(out):: c(:)    ! Infected people travels and contaminates - this is the excretion counter
                                                       ! fed later into the subroutine that integrates B 
            ! real, allocatable, intent(in) :: D(:)    ! Dilution factor for excretion events
            ! real, intent(in) :: "All cholera parameters"

            ! *************** Start subroutine *******************
            ! 
            SELECT case(idis)
            case (0) ! Cholera
            !
            ! Events depend on health status and physical location. 
            active =  people(iagent)%health_status%active_status%status
            stat   =  people(iagent)%health_status%cholera_status%status
            i      =  people(iagent)%location_status%currloc


            if (mask_pop(i)) then ! Check if location is populated
                if (active) then  ! If agent is alive
                    !
                    if (stat == 1) then ! If susceptible (S) *****************************
                        !
                        ! Mobility ==========
                        !
                        ! If agent moves
                        if ((generate_random() <= m) .and. (mask_mob(i))) then ! probability to move = m ; Are you allowed to move? --> mask_mob
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
                        if ((rand <= m) .and. (mask_mob(i))) then
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
                            !
                        end if
                    !===  
                    ! 
                    elseif (stat == 4) then ! If recovered (R) *****************************
                        ! Health ============
                        !
                        ! Lost of immunity R --> S
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
                             end if
                             cyc=.true.
                             n_attempt(i) = n_attempt(i) + 1
                        else
                             n_attempt(i) = n_attempt(i) + 1
                        end if 
                    end do
                end if ! If active
            end if ! mask_pop
            !
            case (1) ! Malaria [Non-functional]
            ! 
            !
            case default
                print *, "Incorrect case, choose disID between: 0 (cholera)"
                STOP
            end SELECT



        end subroutine agents_update


        subroutine agents_age(iagent)
        !
        ! Update age of agent
            implicit none
            integer, intent(in) :: iagent ! Agent
            !
            people(iagent)%agent_ID%age = people(iagent)%agent_ID%age + 1
            !
        end subroutine agents_age


        !============ Functions ===============
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

        function find_masked_face(i,r,cum_distr,sides,mask_grav,mask_pop) result(roll)
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
            integer, intent(in) :: i
            !
            ! Local use only
            integer :: j
            roll = 0
            !
            do j = 1, sides
                if (mask_grav(j) .and. mask_pop(j)) then ! Efficiency
                    
                    if (r <= cum_distr(j)) then
                        !
                        roll = j
                        !
                        exit
                    end if 
                end if
            end do
            !
        end function find_masked_face


        ! Wrap random number subroutine in a function to be able
        ! to use it inside an "if" statement
        function generate_random() result(rand_num)
            implicit none
            real :: rand_num
            !
            call random_number(rand_num) ! Call the intrinsic subroutine
            !
        end function generate_random
















end MODULE mo_agents