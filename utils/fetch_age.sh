#!/bin/bash

# Bash script to download an analyse age structure
# =========================================================
# It creates 
# - A folder 'age_structure' with the original GeoTiff
#   files (in the 'GeoTiff' folder) of the rasterized age structures 
#   in a given country & a corresponding NetCDF file (in 'NetCDF' 
#   folder).
# - 3 figures to asses the sex ratios, spatial
#   homogeneity assumption and the interpolation between
#   age categories.
# - a 'cumm_age.txt' file with the weights of each age in
#   intervals of 1 year (current ABM resolution).
# - The AB model assumes the age distribution is homogeneous
#   within the spatial domain. The accuracy if this assumption
#   must however be evaluated a prior from the generated figures.
# ==========================================================

# Country codes - Senegal: 'sen'

# Age codes - '00': from 0 to 12 months
#             '01':      1 to  4 years
#             '05':      5 to  9 years
#              and so on for: 10,15,20,25,30,35,40,45,50,55,60,65,70,75
#             '80':      80 years or over
#
#              'f': female  'm': male
#--------------
#
# https://hub.worldpop.org/Global1_2000-2020_AgeSexStructures   2000 - 2020
# https://hub.worldpop.org/project/categories?id=8              2015 - 2030 
# 
#--------------------------------------------------------
country1='SEN'                                             # Country code
country2='sen'
year=2015                                                  # Available years are 2020
ages=(0 1 5 10 15 20 25 30 35 40 45 50 55 60 65 70 75 80)  # This is hardcoded WorldPop age structure resolution
DIRECTORY="age_structure_${year}"
wd=$PWD


constrained=true  # If True then we're fetching 2015-2030
                   # otherwise we are using 2000-2020 

ds1=false    # 2020          Constrained
ds2=false   # 2000 - 2020 Unconstrained
ds3=true   # 2015 - 2030 1km  resolution
ds4=false   # 2015 - 2030 100m resolution


ABM=False

if ( ${ds1} ) ; then
    DIRECTORY="Constrained_2020/age_structure_${year}"
elif ( ${ds2} ) ; then
    DIRECTORY="Unconstrained_2000_2020/age_structure_${year}"
elif ( ${ds3} ) ; then
    DIRECTORY="2015_2030_1km/age_structure_${year}"
else 
    DIRECTORY="2015_2030_100m/age_structure_${year}"
fi

if [ ! -d "$DIRECTORY" ]; then

    echo 'Working directory:' ${wd}
    mkdir -p ${DIRECTORY} && cd ${DIRECTORY}
    echo 'Downloading age files'
    echo 'Country:' ${country1} - 'Year:' ${year}

    if ( ${ds3} ) || ( ${ds4} ) ; then
        ages=(00 01 05 10 15 20 25 30 35 40 45 50 55 60 65 70 75 80)  # R2025A uses zero-padded age codes
    fi

    for age in "${ages[@]}"; do
        echo 'Age:' $age
        age_nopad=$((10#$age))  # strip leading zeros so all .nc outputs share one naming convention
                                # the 10# forces base-10 so "00"/"01"/"05" become 0/1/5

        if ( ${ds1} ) ; then
            # Only 2020 is available
            echo 'Only 2020 is available. Setting year --> 2020'
            year=2020
            # Female
            wget -q https://data.worldpop.org/GIS/AgeSex_structures/Global_2000_2020_Constrained_UNadj/2020/${country1}//${country2}_f_${age}_${year}_constrained_UNadj.tif
            gdal_translate -q -of NetCDF ${country2}_f_${age}_${year}_constrained_UNadj.tif ${country2}_f_${age}_${year}.nc
            # Male
            wget -q https://data.worldpop.org/GIS/AgeSex_structures/Global_2000_2020_Constrained_UNadj/2020/${country1}//${country2}_m_${age}_${year}_constrained_UNadj.tif
            gdal_translate -q -of NetCDF ${country2}_m_${age}_${year}_constrained_UNadj.tif ${country2}_m_${age}_${year}.nc
        elif ( ${ds2} ) ; then
            # Female
            wget -q https://data.worldpop.org/GIS/AgeSex_structures/Global_2000_2020_1km/unconstrained/${year}/${country1}/${country2}_f_${age}_${year}_1km.tif
            gdal_translate -q -of NetCDF ${country2}_f_${age}_${year}_1km.tif ${country2}_f_${age}_${year}.nc
            # Male
            wget -q https://data.worldpop.org/GIS/AgeSex_structures/Global_2000_2020_1km/unconstrained/${year}/${country1}/${country2}_m_${age}_${year}_1km.tif
            gdal_translate -q -of NetCDF ${country2}_m_${age}_${year}_1km.tif ${country2}_m_${age}_${year}.nc
        elif ( ${ds3} ) ; then
            # Female
            wget -q https://data.worldpop.org/GIS/AgeSex_structures/Global_2015_2030/R2025A/${year}/${country1}/v1/1km_ua/constrained/${country2}_f_${age}_${year}_CN_1km_R2025A_UA_v1.tif
            gdal_translate -q -of NetCDF ${country2}_f_${age}_${year}_CN_1km_R2025A_UA_v1.tif ${country2}_f_${age_nopad}_${year}.nc
            # Male
            wget -q https://data.worldpop.org/GIS/AgeSex_structures/Global_2015_2030/R2025A/${year}/${country1}/v1/1km_ua/constrained/${country2}_m_${age}_${year}_CN_1km_R2025A_UA_v1.tif
            gdal_translate -q -of NetCDF ${country2}_m_${age}_${year}_CN_1km_R2025A_UA_v1.tif ${country2}_m_${age_nopad}_${year}.nc
        else
            echo 'ds4'
            
        fi    
    done
    
    mkdir -p 'GeoTiff'
    mkdir -p 'NetCDF'

    mv *.nc NetCDF/ 
    mv *.tif GeoTiff/
    cd ${wd}
fi

if [ ! -f "$DIRECTORY/cumm_age.txt" ]; then
echo ' Processing age structure'
echo ${DIRECTORY}
cd ${DIRECTORY}

python3 <<EOF
import xarray as xr
import numpy as np
import matplotlib.pyplot as plt
import scipy 

ages=[1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80]

# Female population
ds_f = xr.open_dataset(f'NetCDF/${country2}_f_0_${year}.nc')['Band1']
# Male population
ds_m = xr.open_dataset(f'NetCDF/${country2}_m_0_${year}.nc')['Band1']
for a in ages:
    ds_dummy = xr.open_dataset(f'NetCDF/${country2}_f_{a}_${year}.nc')['Band1']
    ds_f += ds_dummy
    ds_dummy = xr.open_dataset(f'NetCDF/${country2}_m_{a}_${year}.nc')['Band1']
    ds_m += ds_dummy


# ============= Figure 1 ====================
#print('Spatial heterogeneity ...')
fig,ax = plt.subplots(6,3, sharex = True, sharey = True, dpi = 100)
ages=[0, 1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80]
stats=np.zeros((len(ages),2))
nbins=20
ax = ax.flatten()

for i,a in enumerate(ages):
    plt.subplot(6,3,i+1)

    ds_dummy = xr.open_dataset(f'NetCDF/${country2}_f_{a}_${year}.nc')['Band1']
    x_f =  (np.array(ds_dummy/ds_f)).flatten()
    hist, bins, _ = plt.hist(x_f, bins=nbins, range=(0,0.5), edgecolor = "k", facecolor = "none")
    hist, bins, _ = plt.hist(x_f, bins=nbins, range=(0,0.5), edgecolor = "k", facecolor = 'orange', alpha = 0.3)   

    ds_dummy = xr.open_dataset(f'NetCDF/${country2}_m_{a}_${year}.nc')['Band1'] 
    x_m =  (np.array(ds_dummy/ds_m)).flatten()
    hist, bins, _ = plt.hist(x_m, bins=nbins, range=(0,0.5), edgecolor = "k", facecolor = "none")
    hist, bins, _ = plt.hist(x_m, bins=nbins, range=(0,0.5), edgecolor = "k", facecolor = 'skyblue', alpha = 0.3)   
    
    if ((i != len(ages)-1) & (i != 0)):
        plt.text(0.5,0.5,f'{ages[i]}-{ages[i+1]-1}', transform=plt.gca().transAxes)
    elif (i == 0):
        plt.text(0.5,0.5,f'{ages[i]+1}<', transform=plt.gca().transAxes)
    else:
        plt.text(0.5,0.5,f'>{ages[i]}', transform=plt.gca().transAxes)        
    plt.grid(alpha=0.4)

    stats[i] = np.mean(x_f[~np.isnan(x_f)]), np.mean(x_m[~np.isnan(x_m)])

    if (i == len(ages)-2): plt.xlabel('Proportion of age range in a given grid')
    if (i == 9): plt.ylabel('Counts among all grid points', rotation = 90)

plt.yscale('log')
plt.tight_layout()
plt.savefig('spatial_heterogeneity.pdf',dpi = 100)
plt.close()

print(f'Normalization of dices: {np.sum(stats[:,0]):.3f}, {np.sum(stats[:,1]):.3f}')

# ============= Figure 2 ====================
#print('Sex ratios ...')

#ages_shift = 0.5*(np.roll(np.array(ages),-1)+np.array(ages))#[:-1]
#ages_shift[-1] = ages_shift[-1]*2
#ages_shift[0] = 0

ages_shift = (np.roll(ages,-1)-1)[:-1]
#ages_shift[-1] = 80

plt.plot(ages_shift,stats[:,0][:-1],"-o", label = "Female")
plt.plot(ages_shift,stats[:,1][:-1],"-o", label = "Male")

plt.ylabel("Fraction")
plt.xlabel("Ages [year]")
plt.grid(alpha=0.4)
plt.tight_layout()

plt.ylabel("Fraction")
plt.xlabel("Ages [year]")
plt.grid(alpha=0.4)
plt.tight_layout()
plt.legend(fontsize = 20)

plt.savefig('sex_ratios.pdf',dpi = 100)
plt.close()

# ============= Figure 3 ====================
#print('Interpolation of weights ...')

mean_stats = np.mean(stats[:-1], axis=1)
ages_model = np.arange(int(np.floor(np.min(ages_shift))), int(np.ceil(np.max(ages_shift)))+1)

# PCHIP rather than a cubic B-spline: the input is a CUMULATIVE distribution and an
# unconstrained cubic overshoots between knots, producing stretches where the implied
# density rises with age. MoBILE cannot reproduce a rising density (it would need
# survival > 1) and clamps them, losing shape fidelity.
splines = scipy.interpolate.PchipInterpolator(ages_shift, np.cumsum(mean_stats))
y_new = splines(ages_model).T

plt.subplots(dpi=100, sharey = False)

plt.plot(ages_model, y_new, '-o', color = 'red',ms = 2.5, alpha = 0.4, label = "Interpolation")
plt.scatter(ages_shift,np.cumsum(mean_stats), s=70, color = 'purple', edgecolor = 'k', alpha = 0.4, label = "WorldPop")

plt.xlabel("Age [year]")
plt.ylabel("Cummulative summation of weights")
plt.grid(alpha=0.4)
plt.tight_layout()
plt.yscale('log')
plt.legend()

plt.savefig('interpolation.pdf',dpi = 100)
plt.close()

# ============= Figure 3 ====================
#print('Fit exponential decay ...')

from scipy.optimize import curve_fit
from matplotlib.legend_handler import HandlerTuple

# Recover age structure from cummulative array 
y_inter = np.insert(np.diff(y_new), 0, y_new[0])

def exponential_func(x, A, B):
    """
    Exponential model function: A * exp(B * x) + C
    """
    return (A) * np.exp(-B * x)

# Perform the fitting
x_data = ages_model
y_data = y_inter
popt, pcov = curve_fit(
    exponential_func,
    x_data,
    y_data,
    p0=[0.03,1.0], # Optional: Initial guess for [A, B]
    check_finite=True
)

# Extract results
A_fit, B_fit = popt
perr = np.sqrt(np.diag(pcov)) # Standard error of the fitted parameters

print(f'Fitted mortality = {B_fit:.4f} / year')

fig, ax = plt.subplots(dpi=120)

p0, = plt.plot(ages_model, y_inter, '-o', ms=2.5, color = 'steelblue', lw = 1.5, alpha = 0.8)
p1, = plt.plot(ages_model, exponential_func(ages_model, A_fit, B_fit), color = 'k', ls = 'dashed')

p2, = plt.plot(ages_model, exponential_func(ages_model, A_fit, 1./(61.)), color = 'red', ls = 'dashed')

plt.vlines(61,0,exponential_func(61, A_fit, 1./(61.)), color = 'red', alpha = 0.2)
p3 = plt.scatter(61, exponential_func(61, A_fit, 1./(61.)), color = 'red')
    
plt.vlines(1/B_fit,0,exponential_func(1/B_fit, A_fit, B_fit), color = 'k', alpha = 0.2)
p4 = plt.scatter(1/B_fit, exponential_func(1/B_fit, A_fit, B_fit), color = 'k')

plt.text(0.7,0.6,r'$\gamma_{fit}$ $\sim$'+f'{B_fit:.4f} / year', transform=plt.gca().transAxes, \
        bbox=dict(facecolor='none', edgecolor='black', boxstyle='round,pad=1'))

plt.xlabel("Age [year]")
plt.ylabel("Age structure")
plt.grid(alpha=0.4)

l = ax.legend([p0, p1, p2, (p3, p4)], ['Interpolated WorldPop', 'Exponential fit', 'Literature', 'Mean'],
               handler_map={tuple: HandlerTuple(ndivide=None)})

plt.tight_layout()

plt.savefig('decay_rate_fit.pdf',dpi = 100, transparent = True)
plt.close()

#================= Save cummulative array =======
np.savetxt('cumm_age.txt', y_new, fmt='%.4f', delimiter=' ', newline='\n', header='', footer='', comments='# ', encoding=None)


# ============= Figure 4 ====================

if ${ABM} == True:
    print('ABM')

    # Open simulation
    ds_ABM = xr.open_dataset("../control/control3.nc")["Age"]
    
    # Pre-extract data for the inset (avoids xarray touching ax_inset)
    ds_ABM_norm = ds_ABM / np.sum(ds_ABM)
    x_vals = ds_ABM_norm.coords[ds_ABM_norm.dims[0]].values
    y_vals = ds_ABM_norm.values
    
    fig, ax = plt.subplots(dpi=500)
    
    p0, = plt.plot(ages_model, y_inter, '-o', ms=5.5, color='steelblue', lw=1.5, alpha=0.8)
    
    p21, = plt.plot(ages_model, exponential_func(ages_model, A_fit, 0.0371), color='red', ls='dashed')
    p22, = plt.plot(ages_model, exponential_func(ages_model, A_fit, 0.0411), color='green', ls='-.')
    p1,  = plt.plot(ages_model, exponential_func(ages_model, A_fit, B_fit), color='k', ls='dotted')
    
    plt.vlines(1/0.0371, 0, exponential_func(1/0.0371, A_fit, 0.0371), color='red', alpha=0.2)
    p31 = plt.scatter(1/0.0371, exponential_func(1/0.0371, A_fit, 0.0371), color='red', marker='s')
    plt.vlines(1/0.0411, 0, exponential_func(1/0.0411, A_fit, 0.0411), color='green', alpha=0.2)
    p32 = plt.scatter(1/0.0411, exponential_func(1/0.0411, A_fit, 0.0411), color='green', marker='D')
    plt.vlines(1/B_fit, 0, exponential_func(1/B_fit, A_fit, B_fit), color='k', alpha=0.2)
    p4  = plt.scatter(1/B_fit, exponential_func(1/B_fit, A_fit, B_fit), color='k')
    
    p5, = (ds_ABM/np.sum(ds_ABM)).plot.step(color="orange", ls="solid", alpha=0.9)
    
   # plt.text(0.55, 0.1, r'$\gamma_{fit}$ $\sim$'+f'{B_fit:.4f} / year', transform=plt.gca().transAxes,
   #          bbox=dict(facecolor='none', edgecolor='black', boxstyle='round,pad=1'), fontsize=13)
    
    plt.xlabel("Age [year]", fontsize=13)
    plt.ylabel("Prob. density", fontsize=13)
    plt.yscale('log')
    plt.xticks(fontsize=13)
    plt.yticks(fontsize=13)
    plt.grid(alpha=0.4)
    
    l = ax.legend([p0, p1, p21, p22, (p31, p32, p4), p5],
                  ['Interpolated WorldPop', r'Exponential fit  $\sim 0.0416 / year$', r'Dielmo $\sim 0.0371 / year$', r'Ndiop $\sim 0.0411 / year$', 'Means', 'ABM'],
                  handler_map={tuple: HandlerTuple(ndivide=None)}, fontsize=13)
    
    # --- Inset ---
    from mpl_toolkits.axes_grid1.inset_locator import inset_axes, mark_inset
    
    ax_inset = inset_axes(ax, width="35%", height="35%", loc='upper right')
    
    ax_inset.plot(ages_model, y_inter, '-o', ms=5.5, color='steelblue', lw=1.5, alpha=0.8)
    ax_inset.plot(ages_model, exponential_func(ages_model, A_fit, 0.0371), color='red', ls='dashed')
    ax_inset.plot(ages_model, exponential_func(ages_model, A_fit, 0.0411), color='green', ls='-.')
    ax_inset.plot(ages_model, exponential_func(ages_model, A_fit, B_fit), color='k', ls='dotted')
    ax_inset.vlines(1/0.0371, 0, exponential_func(1/0.0371, A_fit, 0.0371), color='red', alpha=0.2)
    ax_inset.scatter(1/0.0371, exponential_func(1/0.0371, A_fit, 0.0371), color='red', marker='s')
    ax_inset.vlines(1/0.0411, 0, exponential_func(1/0.0411, A_fit, 0.0411), color='green', alpha=0.2)
    ax_inset.scatter(1/0.0411, exponential_func(1/0.0411, A_fit, 0.0411), color='green', marker='D')
    ax_inset.vlines(1/B_fit, 0, exponential_func(1/B_fit, A_fit, B_fit), color='k', alpha=0.2)
    ax_inset.scatter(1/B_fit, exponential_func(1/B_fit, A_fit, B_fit), color='k')
    ax_inset.step(x_vals, y_vals, color="orange", ls="solid", alpha=0.9)  # plain matplotlib, no xarray
    
    ax_inset.set_xlim(22, 28)
    ax_inset.set_ylim(1.4e-2, 1.6e-2)
    ax_inset.set_yscale('log')
    ax_inset.tick_params(labelsize=8, labelbottom=False, labelleft=False)
    ax_inset.set_xlabel('')
    ax_inset.set_ylabel('')
    ax_inset.grid(alpha=0.4)
    
    mark_inset(ax, ax_inset, loc1=3, loc2=4, fc="none", ec="gray", lw=0.8, alpha=0.6)

    ax_inset.yaxis.set_major_formatter(plt.NullFormatter())
    ax_inset.yaxis.set_minor_formatter(plt.NullFormatter())
    
    plt.tight_layout()
    plt.savefig('decay_rate_fit_ABM.pdf', dpi=500, transparent=True)

EOF
fi










