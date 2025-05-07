MODULE mo_control
! This module deals with output and control flags
!
! Miguel Garrido Zornoza 2024 
! mgarrizoraca@gmail.com
!
    implicit none

    ! Control flags *******************************************
    ! These are overwritten by the input command when running MOBILE (when namelist_inout is called)
    logical :: input    =.true.  ! (from flag) [Non-functional]
    logical :: agents   =.true.  ! Use agents, if false the program falls back to density
    logical :: coupling =.false. ! Use VECTRI [Non-functional]
    logical :: radial   =.false. ! If .true. build radial city, otherwise uniform 
    logical :: network  =.false. ! Empirical network flag [Non-functional]
    logical :: gravity  =.true.  ! Use gravity model
    logical :: radiation=.false. ! Use radiation model [Non-functional]
    logical :: diffusion=.false. ! Use diffusion model [Non-functional]
    logical :: random   =.true.  ! Disease initialization - if .true. and rand_seed = .false. random S,I,A,R,B everywhere
                                 !                        - if .true. and rand_seed = .true.  f0 SIAR and random seed for B
                                 !                        - if .false. then f0 SIARB
    logical :: rand_seed=.true.  ! Disease initialization - if .true. random B at a seed and input S,I,A,R

    ! Output --------------------------------------------------
    ! 2D (x,y) Fields
    logical :: out_pop  =.true.   ! Output the steady-state human population density
    logical :: out_Q    =.true.   ! Output connectivity matrix for a given point ixy
    logical :: out_D    =.false.  ! Output distance matrix for source

    ! 3D (x,y,t) Fields
    !
    ! Disease
    logical :: out_S    =.true.  ! Susceptible
    logical :: out_E    =.false. ! Exposed [Non-functional]
    logical :: out_I    =.true.  ! Infected
    logical :: out_A    =.true.  ! Asymptomatic
    logical :: out_R    =.true.  ! Recovered
    !--- Cholera ----
    logical :: out_B    =.true.  ! Bacterial density (could be changed to generic source of disease, e.g., B, V,...)
    logical :: out_F    =.true.  ! Force of infection
    !--- Malaria ----
    logical :: out_V    =.false. ! Vector density
    logical :: out_L    =.false. ! Larval density

    ! Clima
    logical :: out_rain =.true.  ! Rainfall
    logical :: out_t2m  =.true. ! Air temperature

    !----------------------------------------------------------
    integer :: disID                 ! Disease ID (0: Cholera, 1: Malaria)
    character(len=100) :: run_name   ! Name of output files
    character(len=100) :: pop_file   ! Name of population file
    character(len=100) :: rain_file  ! Name of rain/precipitation file
    character(len=100) :: t2m_file   ! Name of temperature file
    !----------------------------------------------------------

    ! https://fortran-lang.org/en/learn/quickstart/arrays_strings/#array-of-strings
    character(len=100) ::  time_names(1)= [character(len=20) :: "time"]
    character(len=100) ::  lon_names(3) = [character(len=20) :: "lon", "longitude", "X"]
    character(len=100) ::  lat_names(3) = [character(len=20) :: "lat", "latitude", "Y"]
    character(len=100) ::  pop_names(4) = [character(len=20) :: "pop", "population", "population density", "Band1"]
    character(len=100) ::  rain_names(5)= [character(len=20) :: "rain", "rainfall", "precipitation", "tp", "precip"]
    character(len=100) ::  temp_names(1)= [character(len=20) :: "temperature"]

    ! Attribute names
    character(len=100) ::  att_names(7) = [character(len=20) :: "standard_name", "long_name", "units", "calendar", "axis", "cell_methods", "_FillValue"]
    
    character(len=100) :: lon_att(7)
    character(len=100) :: lat_att(7)
    character(len=100) :: time_att(7)
    character(len=100) :: rain_att(7)
    character(len=100) :: temp_att(7)
    !----------------------------------------------------------



end MODULE mo_control