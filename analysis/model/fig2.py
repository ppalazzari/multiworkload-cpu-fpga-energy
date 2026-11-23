import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim as S, statistics as st
W=['QP','NB','DE','IM']; N=10
tF={'QP':45.17,'NB':44.53,'DE':60.11,'IM':61.31}; tC29={'QP':88.55,'NB':91.33,'DE':51.99,'IM':30.02}
def stat(x,t,s):
    c=sum(1 for w in W if x[w]>0); TF=sum(x[w]*tF[w] for w in W)+c*t; TC=sum((N-x[w])*tC29[w] for w in W)
    if s and x['NB']<N and x['QP']<N: TC+=s
    return max(TF,TC)
def shared(x,t,s,interf=True):
    par=S.par; Sm=S.S; segs=[];tt=0
    for w in W:
        if x[w]>0: tt+=t; d=x[w]*par[w][0]; segs.append((tt,tt+d,w)); tt+=d
    TF=tt; tc=0; first=True
    for u in W:
        n=N-x[u]
        if n<=0: continue
        if s and u=='NB' and not first: tc+=s
        first=False; rem=n
        while rem>1e-9:
            v=None; nxt=float('inf')
            for a,b,w in segs:
                if a<=tc<b: v=w; nxt=b; break
                if a>tc: nxt=min(nxt,a); break
            r=1/(par[u][1]*(Sm[u][v] if (v and interf) else 1.0)); dt=min(rem/r,nxt-tc); rem-=r*dt; tc+=dt
    return max(TF,tc)
P={'sh':(745.3+744.7+740.4)/3,'st':(729.1+737.5+737.0)/3}
out={}
for reg,f,fun,s in (('sh','../../data/derived/casuali_shared_risultati.txt',shared,61),('st','../../data/derived/casuali_static_risultati.txt',stat,96)):
    rows=[]
    for l in open(f):
        t,a,Tp,Tm,Ep,Em=l.split(); x={k:int(v) for k,v in (p.split(':') for p in a.split(','))}
        T0=fun(x,5.4,0); T1=fun(x,5.9,0); T2=fun(x,5.9,s)
        Tn=shared(x,5.9,0,False) if reg=='sh' else T1
        rows.append((t,float(Ep)+P[reg]*(T1-T0)/1e3,float(Ep)+P[reg]*(T2-T0)/1e3,float(Em),float(Ep)+P[reg]*(Tn-T0)/1e3))
    out[reg]=rows
ew=[(2702.6,2657.2,2345.0,2646.9,2715.9),(2772.6,2679.2,2349.7,2729.5,2800.1),(3046.1,2969.4,2652.5,2977.9,3106.6),(3152.9,3021.8,2777.5,3132.9,3173.3),(3440.4,3374.4,2937.1,3358.2,3476.9),(3485.4,3363.6,2766.4,3454.3,3499.6),(3565.2,3448.9,2636.7,3541.7,3595.7),(3741.9,3640.9,3220.3,3720.8,3754.6),(3749.4,3662.2,3410.8,3727.1,3770.3),(3882.8,3778.2,2923.8,3859.2,3914.4),(3897.8,3819.6,3552.0,3877.6,3939.9),(3959.8,3862.9,3211.0,3934.9,3994.4)]

import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
import statistics as st
R=[r for r in out['sh'] if not r[0].startswith('opt')]
print('shared random noint: mean abs err', round(st.mean(abs(r[3]/r[4]-1)*100 for r in R),1), 'max', round(max(abs(r[3]/r[4]-1)*100 for r in R),1))
def sp(a,b):
    n=len(a); ra={i:k for k,i in enumerate(sorted(range(n),key=lambda i:a[i]))}; rb={i:k for k,i in enumerate(sorted(range(n),key=lambda i:b[i]))}
    return 1-6*sum((ra[i]-rb[i])**2 for i in range(n))/(n*(n*n-1))
print('spearman noint',round(sp([r[4] for r in R],[r[3] for r in R]),3),'interf',round(sp([r[1] for r in R],[r[3] for r in R]),3),'interf+nb',round(sp([r[2] for r in R],[r[3] for r in R]),3))
fig,ax=plt.subplots(1,2,figsize=(7.16,3.2))
a=ax[0]
S_=[r for r in out['sh'] if not r[0].startswith('opt')]; P_=[r for r in out['st'] if not r[0].startswith('opt')]
a.scatter([r[4] for r in S_],[r[3] for r in S_],s=16,marker='D',facecolors='none',edgecolors='C3',linewidths=0.7,label='shared, no interf.')
a.scatter([r[1] for r in S_],[r[3] for r in S_],s=14,marker='o',facecolors='none',edgecolors='C0',linewidths=0.8,label='shared, interf.')
a.scatter([r[2] for r in S_],[r[3] for r in S_],s=14,marker='o',color='C0',label='shared, interf. + NB setup')
a.scatter([r[1] for r in P_],[r[3] for r in P_],s=14,marker='s',facecolors='none',edgecolors='C1',linewidths=0.8,label='partitioned')
a.scatter([r[2] for r in P_],[r[3] for r in P_],s=14,marker='s',color='C1',label='partitioned + NB setup')
for reg in ('sh','st'):
    O=[r for r in out[reg] if r[0].startswith('opt')]; a.scatter([r[2] for r in O],[r[3] for r in O],s=50,marker='*',color='k',zorder=3)
a.set_title('(a) random allocations, $N_w = 10$',fontsize=9)
b=ax[1]
yerr=[[e[0]-e[3] for e in ew],[e[4]-e[0] for e in ew]]
b.errorbar([e[2] for e in ew],[e[0] for e in ew],yerr=yerr,fmt='D',ms=4,mfc='none',mec='C3',ecolor='C3',elinewidth=0.6,capsize=1.5,label='no interference')
b.errorbar([e[1] for e in ew],[e[0] for e in ew],yerr=yerr,fmt='o',ms=4,color='C0',elinewidth=0.6,capsize=1.5,label='interference')
b.scatter([2458.2],[2472.2],s=60,marker='*',color='k',zorder=3)
b.set_title('(b) equal-work allocations, $N_w = 30$, shared cores',fontsize=9)
for x in ax:
    lo=min(x.get_xlim()[0],x.get_ylim()[0]); hi=max(x.get_xlim()[1],x.get_ylim()[1])
    x.plot([lo,hi],[lo,hi],'k--',lw=0.7); x.set_xlim(lo,hi); x.set_ylim(lo,hi)
    x.set_xlabel('predicted energy (kJ)'); x.set_ylabel('measured energy (kJ)')
    x.legend(fontsize=6.5,loc='lower right',frameon=False,handletextpad=0.3,borderaxespad=0.3)
fig.tight_layout(); fig.savefig('fig_random.pdf')
