! --AB--
MODULE mo_advect

USE mo_constants  
!USE mo_control -> nnumeric is now passed as explicit input
!USE mo_vectri  -> iounit is now passed as explicit input


CONTAINS


SUBROUTINE advection(rbox0,rfrac,rarray,na,nnumeric,iounit)
!--------------------------------------------------------- 
! VECTRI
!
! Tompkins AM. 2011, ICTP
! tompkins@ictp.it
!
!
! advection: routine to move on boxes by rfrac amount
!
! 1: hm04 numerics - move on by integer boxes (inaccurate)
! 2: bilinear forward (inverse semi-Lagrangian) advection
! 3: bilinear semi-Lagrangian advection (default, diffusive but fast)
! 4: cubic semi-Lagrangian advection
! 5: gtd cubic semi-Lagrangian advection
! 5: hans-C spline 
!----------------------------------------------------------

  IMPLICIT NONE
  INTEGER, INTENT(IN) :: nnumeric  ! Selects advection scheme
  INTEGER, INTENT(IN) :: iounit
  INTEGER,  INTENT(IN)   :: na
  REAL, INTENT(IN)   :: rfrac 
  REAL, INTENT(IN)   :: rbox0 

  REAL, INTENT(INOUT) :: rarray(0:na)
!  REAL, INTENT(INOUT) :: wrap_array(0:na)

  ! local arrays
  REAL, ALLOCATABLE :: zarray1(:),zarray2(:)

  ! local integers 
  INTEGER :: i,ideli,idx,im1,ip1
  ! local real scalars

  REAL:: zfrac, zdep, zalfa, zalfa2 &
&           ,zdel &
&           ,znew &
&           ,y0,y1,y2,y3,a0,a1,a2,a3


  zfrac=REAL(na)*rfrac

  ALLOCATE(zarray2(0:na))
  zarray2=1.0
  zarray2(0)=rbox0

  SELECT CASE(nnumeric)
    CASE(1) ! hm04 numerics, integer box shifting 

      ideli=NINT(zfrac)
      ALLOCATE(zarray1(0:na))
      zarray1=rarray
      DO i=0,na   
        idx=i+ideli      ! new index
        idx=MIN(na,idx)   ! don't move beyond end of array
        zdel=zarray1(i)*zarray2(i)
        rarray(idx)=rarray(idx)+zdel
        rarray(i)  =rarray(i)  -zdel
      ENDDO
      DEALLOCATE(zarray1)

    CASE(2) ! split box shifting 

      ideli=FLOOR(zfrac)
      zalfa=zfrac-ideli

      ALLOCATE(zarray1(0:na))
      zarray1=rarray ! copy input array
      DO i=0,na   
        im1=i+ideli      ! new index
        ip1=im1+1
        im1=MIN(na,im1)   ! 
        ip1=MIN(na,ip1)   ! don't move beyond end of array
        ! zarray2 means that part of box 0 is left behind:
        zdel=zarray1(i)*zarray2(i) 
        rarray(im1)=rarray(im1)+zdel*(1-zalfa)
        rarray(ip1)=rarray(ip1)+zdel*zalfa
        rarray(i)  =rarray(i)  -zdel
      ENDDO
      DEALLOCATE(zarray1)


    CASE(3) ! semi lagrangian bilin interpolation 

      ALLOCATE(zarray1(-4:2*na))
      zarray1(:)=0.0
      zarray1(0:na)=rarray ! zarray stores the original array
      rarray(:)=0.0

! 1.0-rbox0 fraction of the box0 contents are not advected
      rarray(0)=(1.0-rbox0)*zarray1(0)
      zarray1(0)=rbox0*zarray1(0)

! maybe we need cyclic ??? vector bites lays and then goonotropic cycle starts.
      DO i=0,2*na-1   
        ! departure point
        zdep=MAX(-2.0,REAL(i)-zfrac)

        ! define bounding points 
        im1=FLOOR(zdep)
        ip1=im1+1      
        zalfa=zdep-im1

        znew=zalfa*zarray1(ip1)+(1.0-zalfa)*zarray1(im1)
        idx=MIN(i,na)
        rarray(idx)=rarray(idx)+znew
      ENDDO
      DEALLOCATE(zarray1)
   
    CASE(4) ! semi lagrangian cubic interpolation 
      ALLOCATE(zarray1(-4:2*na))
      zarray1=0.0
      zarray1(0:na)=rarray 
      rarray=0.0
      DO i=0,2*na-1   
        ! departure point
        zdep=MAX(-2.0,REAL(i)-zfrac)

        ! define bounding points 
        im1=FLOOR(zdep)
        ip1=im1+1

        zalfa=zdep-im1
        zalfa2=zalfa*zalfa
        y0=zarray1(im1-1)
        y1=zarray1(im1)
        y2=zarray1(ip1)
        y3=zarray1(ip1+1)

        a0 = y3 - y2 - y0 + y1
        a1 = y0 - y1 - a0
        a2 = y2 - y0
        a3 = y1

!        a0 = -0.5*y0 + 1.5*y1 - 1.5*y2 + 0.5*y3;
!        a1 = y0 - 2.5*y1 + 2*y2 - 0.5*y3;
!        a2 = -0.5*y0 + 0.5*y2;
!        a3 = y1;

        znew=a0*zalfa*zalfa2+a1*zalfa2+a2*zalfa+a3
        idx=MIN(i,na)
        rarray(idx)=rarray(idx)+znew
      ENDDO
      DEALLOCATE(zarray1)

    CASE(5) ! gtd semi lagrangian cubic interpolation 
      ALLOCATE(zarray1(-4:na))
      zarray1=0.0
      zarray1(0:na)=rarray 
      rarray=0.0

      zalfa=1.0-zfrac+FLOOR(zfrac)
      a0 = -(zalfa*(1.0 - zalfa*zalfa))/6.0
      a1 = (zalfa*(1.0 + zalfa)*(2.0 - zalfa))/2.0
      a2 = ((1.0 - zalfa*zalfa)*(2.0 - zalfa))/2.0
      a3 = -(zalfa*(1.0 - zalfa)*(2.0 - zalfa))/6.0

      DO i=0,2*na   
        ! departure point and bounding 
        zdep=MAX(-3.0+zalfa,REAL(i)-zfrac)
        im1=FLOOR(zdep)
        ip1=im1+1      
        y0=zarray1(im1-1)
        y1=zarray1(im1)
        y2=zarray1(ip1)
        y3=zarray1(ip1+1)
        znew=a0*y0 + a1*y1 + a2*y2 + a3*y3        
        idx=MIN(i,na) ! limit to array end
        rarray(idx)=rarray(idx)+znew
      ENDDO
      DEALLOCATE(zarray1)
!   return(a0*mu*mu2+a1*mu2+a2*mu+a3);

!    CASE(4)  ! Catmull-Rom splines. 
!   a0 = -0.5*y0 + 1.5*y1 - 1.5*y2 + 0.5*y3;
!   a1 = y0 - 2.5*y1 + 2*y2 - 0.5*y3;
!   a2 = -0.5*y0 + 0.5*y2;
!   a3 = y1;
    CASE DEFAULT
      WRITE(iounit,*)'incorrect advection scheme'
      STOP
  END SELECT

  RETURN
END SUBROUTINE ADVECTION


END MODULE mo_advect