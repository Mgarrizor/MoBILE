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
year=2020                                                  # Available years are 2020
ages=(0 1 5 10 15 20 25 30 35 40 45 50 55 60 65 70 75 80)  # This is hardcoded WorldPop age structure resolution
DIRECTORY="age_structure"

if [ ! -d "$DIRECTORY" ]; then

    mkdir -p ${DIRECTORY} && cd ${DIRECTORY}
    echo 'Downloading age files'
    for age in ${ages[@]}; do
        echo 'Age:' $age
        # Female
        wget -q https://data.worldpop.org/GIS/AgeSex_structures/Global_2000_2020_Constrained_UNadj/2020/${country1}//${country2}_f_${age}_${year}_constrained_UNadj.tif
        gdal_translate -q -of NetCDF ${country2}_f_${age}_${year}_constrained_UNadj.tif ${country2}_f_${age}_${year}_constrained_UNadj.nc
        # Male
        wget -q https://data.worldpop.org/GIS/AgeSex_structures/Global_2000_2020_Constrained_UNadj/2020/${country1}//${country2}_m_${age}_${year}_constrained_UNadj.tif
        gdal_translate -q -of NetCDF ${country2}_m_${age}_${year}_constrained_UNadj.tif ${country2}_m_${age}_${year}_constrained_UNadj.nc
    done
    
    mkdir -p 'GeoTiff'
    mkdir -p 'NetCDF'

    mv *.nc NetCDF/ 
    mv *.tif GeoTiff/
    cd ..
fi

if [ ! -f "$DIRECTORY/cumm_age.txt" ]; then
echo ' Processing age structure'

cd ${DIRECTORY}
python3 <<EOF
import xarray as xr
import numpy as np
import matplotlib.pyplot as plt
import scipy 

ages=[1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80]

# Female population
ds_f = xr.open_dataset(f'NetCDF/${country2}_f_0_${year}_constrained_UNadj.nc')['Band1']
# Male population
ds_m = xr.open_dataset(f'NetCDF/${country2}_m_0_${year}_constrained_UNadj.nc')['Band1']
for a in ages:
    ds_dummy = xr.open_dataset(f'NetCDF/${country2}_f_{a}_${year}_constrained_UNadj.nc')['Band1']
    ds_f += ds_dummy
    ds_dummy = xr.open_dataset(f'NetCDF/${country2}_m_{a}_${year}_constrained_UNadj.nc')['Band1']
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

    ds_dummy = xr.open_dataset(f'NetCDF/${country2}_f_{a}_${year}_constrained_UNadj.nc')['Band1']
    x_f =  (np.array(ds_dummy/ds_f)).flatten()
    hist, bins, _ = plt.hist(x_f, bins=nbins, range=(0,0.5), edgecolor = "k", facecolor = "none")
    hist, bins, _ = plt.hist(x_f, bins=nbins, range=(0,0.5), edgecolor = "k", facecolor = 'orange', alpha = 0.3)   

    ds_dummy = xr.open_dataset(f'NetCDF/${country2}_m_{a}_${year}_constrained_UNadj.nc')['Band1'] 
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

splines = scipy.interpolate.make_interp_spline(ages_shift,np.cumsum(mean_stats), k = 3)
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
np.savetxt('cumm_age.txt', y_new, fmt='%.3f', delimiter=' ', newline='\n', header='', footer='', comments='# ', encoding=None)
EOF
fi










