import numpy as np, json
c=299792458.0
out={}
# ---------------- Antenne patch sur feutre ----------------
f0=2.45e9; h=3e-3; er=1.3; tand=0.02
lam0=c/f0
def patch_dims(er,h,f0):
    W=c/(2*f0)*np.sqrt(2/(er+1))
    ee=(er+1)/2+(er-1)/2*(1+12*h/W)**-0.5
    dL=0.412*h*(ee+0.3)*(W/h+0.264)/((ee-0.258)*(W/h+0.8))
    L=c/(2*f0*np.sqrt(ee))-2*dL
    return W,L,ee,dL
W,L,ee,dL=patch_dims(er,h,f0)
G1=W/(120*lam0)*(1-(2*np.pi/lam0*h)**2/24)
Redge=1/(2*G1)
y0=L/np.pi*np.arccos(np.sqrt(50/Redge))
bw_frac=3.77*(er-1)/er**2*(W/L)*(h/lam0)
Qr=1/(np.sqrt(2)*bw_frac)
Qd=1/tand
Rs=0.05
w=2*np.pi*f0; delta_eq=2*Rs/(w*4e-7*np.pi); Qc=h/delta_eq
Qt=1/(1/Qr+1/Qd+1/Qc)
eta=(1/Qr)/(1/Qr+1/Qd+1/Qc)
bw10=0.667*f0/Qt
# microstrip 50 ohm width (Hammerstad)
def ms_z0(wh,er):
    e_eff=(er+1)/2+(er-1)/2*(1+12/wh)**-0.5
    if wh<=1: return 60/np.sqrt(e_eff)*np.log(8/wh+wh/4)
    return 120*np.pi/(np.sqrt(e_eff)*(wh+1.393+0.667*np.log(wh+1.444)))
from scipy.optimize import brentq
wh50=brentq(lambda x: ms_z0(x,er)-50,0.5,30)
out['ant']=dict(W=W*1e3,L=L*1e3,eeff=ee,dL=dL*1e3,Redge=Redge,y0=y0*1e3,bw_frac=bw_frac,Qr=Qr,Qd=Qd,Qc=Qc,Qt=Qt,eta=eta,bw10=bw10/1e6,wh50=wh50,w50=wh50*h*1e3,
  gnd=(W+6*h*2)*1e3, gndL=(L+6*h*2)*1e3, lam0=lam0*1e3, Rs=Rs)
# moisture detuning
eps_sw=76-15j
rows=[]
for v in [0,0.0025,0.005,0.01,0.02,0.05]:
    e_c=(1-v)*er+v*eps_sw
    er_w=e_c.real; td=-e_c.imag/e_c.real
    # tand dry offset
    td_tot=(tand*er*(1-v)+(-eps_sw.imag)*v)/er_w
    W_,L_,ee_,dL_=patch_dims(er_w,h,f0)   # for reference only
    eew=(er_w+1)/2+(er_w-1)/2*(1+12*h/W)**-0.5
    dLw=0.412*h*(eew+0.3)*(W/h+0.264)/((eew-0.258)*(W/h+0.8))
    fres=c/(2*(L+2*dLw)*np.sqrt(eew))
    bwf=3.77*(er_w-1)/er_w**2*(W/L)*(h/lam0)
    Qr_=1/(np.sqrt(2)*bwf); Qd_=1/td_tot
    eta_=(1/Qr_)/(1/Qr_+1/Qd_+1/Qc); Qt_=1/(1/Qr_+1/Qd_+1/Qc)
    rows.append(dict(v=v*100,er=er_w,tand=td_tot,fres=fres/1e6,df=(fres-f0)/1e6,eta=eta_,Qt=Qt_))
out['moist']=rows
# bending (chord model)
bend=[]
for R in [200,150,100]:
    x=L/(2*R*1e-3); fac=np.sin(x)/x; df=(1/fac-1)*f0/1e6
    bend.append(dict(R=R,df=df))
out['bend']=bend
# link budget
def fspl(d): return 20*np.log10(4*np.pi*d/lam0)
G_ant=10*np.log10(10**(6.6/10)*eta)  # D~6.6 dBi
lb=[]
for d,shadow in [(0.6,25),(1.5,25),(10,12)]:
    Ptx=0; Gtx=G_ant; Grx=-2.0
    prx=Ptx+Gtx+Grx-fspl(d)-shadow
    lb.append(dict(d=d,shadow=shadow,fspl=fspl(d),prx=prx,m1m=prx+96,mcoded=prx+103))
out['link']=lb; out['G_ant']=G_ant
# ---------------- Bilan de puissance ----------------
V=3.3; eta_dc=0.90; Vbat=3.7
I_idle=dict(mcu=1.00,afe=0.25,imu=0.30,bridge=0.12,tempsens=0.01,flash=0.01,modem_psm=0.005,pmic=0.015)
I_acq_idle=sum(I_idle.values())
dI_cpu=7.0
FCPU=128e6; cpm=4
macs_casc=128000; macs_cnn=222000
cycles=dict(nlms=700*250, dae=macs_casc*cpm*250/128, cnn=macs_cnn*cpm/2.0, prep=50000, qrs=100000, fft=15000, os=300000)
cyc_tot=sum(cycles.values()); duty=cyc_tot/FCPU
I_cpu_avg=dI_cpu*duty
I_ble_peak=8.0; ble_ev=0.003; ci=0.25
I_ble=I_ble_peak*ble_ev/ci
mj_beacon=2*250+3*60+20*45   # mA.s
beacon_period=3600
I_nb=mj_beacon/beacon_period
I_nom=I_acq_idle+I_cpu_avg+I_ble+I_nb
P_rail=I_nom*V; P_bat=P_rail/eta_dc; I_bat=P_bat/Vbat
k=0.90*0.85*0.85
def auton(C,I): return C*k/I
out['pwr']=dict(I_idle=I_idle,I_acq_idle=I_acq_idle,cycles=cycles,cyc_tot=cyc_tot,duty=duty,I_cpu_avg=I_cpu_avg,I_ble=I_ble,
   mj_beacon=mj_beacon,I_nb=I_nb,I_nom=I_nom,P_rail=P_rail,P_bat=P_bat,I_bat=I_bat,k=k,
   aut250=auton(250,I_bat),aut150=auton(150,I_bat),aut100=auton(100,I_bat))
# scenario degrade: DAE ungated @ 2x (160 MHz?), coded PHY, beacon 10 min, SOS state
I_ble_c=I_ble*8
I_nb_d=mj_beacon/600
I_cpu_d=dI_cpu*min(1,duty*1.5)
I_deg=I_acq_idle+I_cpu_d+I_ble_c+I_nb_d
Pbat_d=I_deg*V/eta_dc; Ibat_d=Pbat_d/Vbat
out['pwr']['deg']=dict(I=I_deg,I_bat=Ibat_d,aut250=auton(250,Ibat_d))
# deep sleep
I_ds=0.006+0.001+0.003+0.0002+0.0001+0.004+0.005+0.010
out['pwr']['I_ds']=I_ds
out['pwr']['ds_days']=250*0.9/ (I_ds*V/eta_dc/Vbat)/24
# charge
Icc=0.5*250; t_chg=250/Icc*1.15
out['chg']=dict(Icc=Icc,t=t_chg)
# SAR scaling
out['sar']=dict(ble_mW=1.0,nb_duty=2.0/3600,nb_avg_mW=200*2.0/3600)
json.dump(out,open('design.json','w'),indent=1)
print(json.dumps(out,indent=1))
