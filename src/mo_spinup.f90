MODULE mo_spinup
! This module contains spin-up methods
! to deal with the slow adjustment of 
! immunity.

! Miguel Garrido Zornoza 2025
! mgarrizoraca@gmail.com


implicit none
! Direct integration

CONTAINS 
subroutine DI(x_d,tol_SU,conv,SU_old)

    implicit none

    real, intent(inout) :: SU_old ! Convergence test from last time step
    real, allocatable, intent(in) :: x_d(:) ! Array with values averaged over the whole spatial domain (daily time step)
    real, intent(in) :: tol_SU              ! Tolerance of convergence
    logical, intent(out) :: conv            ! Convergence boolean

    ! Local use only
    real :: SU_new 
    real :: eps_SU   ! Epsilon Spin-Up

    SU_new = mean(x_d)
    ! To Do: Annual mean for different age categories

    eps_SU = abs(SU_new-SU_old) 
    WRITE(*,'(1a1,A20,F6.4,A5,F6.4)', advance='no') char(13),'Spin-up convergence ',eps_SU,' <=? ',tol_SU

    if (eps_SU <= tol_SU) then
        conv = .true.
    else  
        SU_old = SU_new
    end if

end subroutine DI

! Anderson acceleration method
subroutine AA()

    implicit none

end subroutine AA


function mean(x) result(m)
    
    implicit none

    real, allocatable, intent(in) :: x(:)
    real :: m ! Mean of array x(:)

    ! Local use only
    integer :: n

    n = size(x)
    if (n /= 0) then
        m = sum(x(:))/size(x(:))
    else 
        print*, 'Cannot compute mean during Spin-up --> Exit'
        STOP
    end if

end function mean

end MODULE mo_spinup