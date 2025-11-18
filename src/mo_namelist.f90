MODULE mo_namelist
! This module deals with the NAMELIST(S) information

! Author: Miguel Garrido Zornoza (2024)
! Contact: mgarrizoraca@gmail.com
!

    use, intrinsic :: iso_fortran_env, only: stderr => error_unit
    use mo_const
    use mo_control

    
    implicit none

    CONTAINS

        subroutine namelist_inout(run_name,disID,nsteps,seed,spin_up)
            implicit none
            
            character(len=100), intent(out):: run_name
            integer, intent(out) :: disID, nsteps, seed, spin_up
            
            ! Local use only
            character(len=1000) :: line
            integer:: file_unit, iostats
            
            ! Define namelist
            namelist /INOUT/ run_name, disID, nsteps, seed, spin_up

            ! Does the file exist?
            inquire (file='namelist.nml', iostat=iostats)

             if (iostats /= 0) then
                 write (stderr, '("Error: namelist file does not exist")')
                 return
             end if

            ! Open and read namelist
            open (action='read', file='namelist.nml', iostat=iostats, newunit=file_unit)
            read (nml=INOUT, iostat=iostats, unit=file_unit)

            ! If file exists but reading failed
            if (iostats /= 0) then
                write (stderr, '("Error: invalid namelist format")')
                ! Output line where failure occured
                ! https://degenerateconic.com/namelist-error-checking.html
                backspace(file_unit)
                read(file_unit,fmt='(A)') line
                write(stderr,'(A)') 'Invalid line in namelist is: '//trim(line)
                STOP
            end if
            
            close (file_unit)

        end subroutine namelist_inout

        subroutine namelist_human(pop_file,nagent,imm_file)
            implicit none

            character(len=100), intent(out):: pop_file, imm_file
            integer, intent(out) :: nagent
            
            ! Local use only
            character(len=1000) :: line
            integer:: file_unit, iostats
            
            ! Define namelist
            namelist /HUMAN/ pop_file, nagent, imm_file

            ! Does the file exist?
            inquire (file='namelist.nml', iostat=iostats)

             if (iostats /= 0) then
                 write (stderr, '("Error: namelist file does not exist")')
                 return
             end if

            ! Open and read namelist
            open (action='read', file='namelist.nml', iostat=iostats, newunit=file_unit)
            read (nml=HUMAN, iostat=iostats, unit=file_unit)

            ! If file exists but reading failed
            if (iostats /= 0) then
                write (stderr, '("Error: invalid namelist format")')
                ! Output line where failure occured
                ! https://degenerateconic.com/namelist-error-checking.html
                backspace(file_unit)
                read(file_unit,fmt='(A)') line
                write(stderr,'(A)') 'Invalid line in namelist is: '//trim(line)
            end if

            if (len(trim(imm_file)) /= 0) then
                print *, '--> Immunity forcing ', imm_file
                in_imm = .true.
            end if
            
            close (file_unit)
            
        end subroutine namelist_human



        subroutine namelist_clima(rain_file,t2m_file,area_file)
            implicit none

            character(len=100), intent(out):: rain_file, t2m_file, area_file
            
            ! Local use only
            character(len=1000) :: line
            integer:: file_unit, iostats
            
            ! Define namelist
            namelist /CLIMA/ rain_file, t2m_file, area_file

            ! Does the file exist?
            inquire (file='namelist.nml', iostat=iostats)

             if (iostats /= 0) then
                 write (stderr, '("Error: namelist file does not exist")')
                 return
             end if

            ! Open and read namelist
            open (action='read', file='namelist.nml', iostat=iostats, newunit=file_unit)
            read (nml=CLIMA, iostat=iostats, unit=file_unit)

            ! If file exists but reading failed
            if (iostats /= 0) then
                write (stderr, '("Error: invalid namelist format")')
                ! Output line where failure occured
                ! https://degenerateconic.com/namelist-error-checking.html
                backspace(file_unit)
                read(file_unit,fmt='(A)') line
                write(stderr,'(A)') 'Invalid line in namelist is: '//trim(line)
            end if

            if (len(trim(rain_file)) == 0) then
                print *, 'No rainfall input'
                out_rain = .false.
            end if 

            if (len(trim(t2m_file)) == 0) then
                print *, 'No temperature input'
                out_t2m = .false.
            end if

            if (len(trim(area_file)) == 0) then
                print *, 'No area input'
                if (agents) then 
                    STOP 
                end if
            end if

            
            close (file_unit)
            
        end subroutine namelist_clima


        subroutine namelist_const
        ! - Contains all model constants
        ! - Overwrites default values selected 
        !   by case at mo_const.f90

        ! - Especially usefull for sensitivity analysis and calibration 

        ! - You can use a NAMELIST to input values for specific parameters, and it is perfectly valid 
        !   to provide only a subset of the parameters defined in the NAMELIST. 
        !   When you input a single parameter value, the program will update only that specific parameter, 
        !   while the others will retain their default or previously assigned values.
            implicit none

            ! Local use only
            character(len=1000) :: line
            integer:: file_unit, iostats

            ! Define namelist
            ! - We should have here all model parameters that are being changed to their params.txt value
            !
            namelist /CONST/ mu_B, theta_e, theta_p, mu, rho, sigma, gamma, alpha, beta, & ! cholera disease params
                             m_long, m_short, D_grav, D_pop, H_0,                        & ! mobility params gravity model
                             B_0, fS_0, fI_0, fA_0, fR_0,                                & ! initial conditions
                             K_h, b_rate                                             ! malaria params
                             
            ! Does the file exist?
            inquire (file='namelist.nml', iostat=iostats)

             if (iostats /= 0) then
                 write (stderr, '("Error: namelist file does not exist")')
                 return
             end if

            ! Open and read namelist
            open (action='read', file='namelist.nml', iostat=iostats, newunit=file_unit)
            read (nml=CONST, iostat=iostats, unit=file_unit)

            
            ! If file exists but reading failed
            if (iostats /= 0) then
                write (stderr, '("Error: invalid namelist format")')
                ! Output line where failure occured
                ! https://degenerateconic.com/namelist-error-checking.html
                backspace(file_unit)
                read(file_unit,fmt='(A)') line
                write(stderr,'(A)') 'Invalid line in namelist is: '//trim(line)
            end if
            
            close (file_unit)
        end subroutine namelist_const




















end MODULE mo_namelist