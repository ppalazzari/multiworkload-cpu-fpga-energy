import sim as S, statistics as st, itertools
S.tcfg=5.9
W=['QP','NB','DE','IM']; N={w:30 for w in W}
rho={'QP':507.4,'NB':512.4,'DE':359.6,'IM':243.9}
raw="""A opt 2514.2 2441.3
A nb30qp21 2829.6 2711.1
A qp30nb21 2927.3 2787.2
A nb30de21 3865.5 3543.3
A qp30de21 3091.6 2977.9
A de30nb21 3693.8 3454.3
A de30qp21 3235.6 3137.0
A allcpu 5106.2 4876.2
A opt 2554.6 2475.6
A nb30im21 4273.9 3861.0
A qp30im21 3723.1 3429.0
A im30nb21 4313.8 3934.9
A im30qp21 4094.8 3748.3
A de30im21 3973.4 3727.1
A im30de21 4171.0 3877.6
A opt 2536.2 2462.1
A nb30im21 4265.8 3859.2
A qp30im21 3621.8 3358.2
A im30nb21 4329.2 3948.0
A im30qp21 4050.5 3720.8
B opt 2540.4 2476.8
B im30de21 4207.1 3939.9
B de30im21 3974.6 3761.0
B im30qp21 4022.2 3735.4
B im30nb21 4300.3 3971.6
B qp30im21 3713.0 3451.8
B nb30im21 4266.3 3904.7
B allfpga 6284.8 4638.3
B opt 2562.0 2498.1
B de30qp21 3245.6 3168.9
B de30nb21 3684.6 3490.4
B qp30de21 3125.5 3034.3
B nb30de21 3859.5 3587.0
B qp30nb21 2888.9 2800.1
B nb30qp21 2797.3 2715.9
B opt 2512.7 2463.6
B de30qp21 3249.4 3173.3
B de30nb21 3694.3 3499.6
B qp30de21 3226.6 3106.6
B nb30de21 3866.8 3595.7"""
d={}
for l in raw.splitlines():
    n,t,T,E=l.split(); d.setdefault(t,[]).append((n,float(T),float(E)))
def alloc(t):
    x={w:0 for w in W}
    if t=='opt': x.update(QP=30,NB=25)
    elif t=='allfpga': x={w:30 for w in W}
    elif t=='allcpu': pass
    else:
        a,b=t[:2].upper(),t[4:6].upper(); x[a]=int(t[2:4]); x[b]=int(t[6:8])
    return x
opt=st.mean(e for n,T,e in d['opt']); print('opt mean',round(opt,1),'sd',round(st.stdev([e for n,T,e in d['opt']]),1),'n',len(d['opt']))
rows=[]
for t,R in d.items():
    x=alloc(t); Tp,Ep=S.sim(x,N,W,W,714.8,True)
    E=[e for n,T,e in R]; Tm=st.mean(T for n,T,e in R)
    units={w:x[w] for w in W if x[w]>0}
    rb=sum(x[w]*rho[w] for w in W)/sum(x.values()) if t not in('allcpu','allfpga','opt') else None
    nodes=''.join(n for n,_,_ in R)
    rows.append((rb if rb else 0,t,len(E),nodes,st.mean(E),(max(E)-min(E)) if len(E)>1 else 0,Ep,Tm,Tp))
for rb,t,n,nodes,E,rg,Ep,Tm,Tp in sorted(rows,key=lambda r:-r[0]):
    print(f"{t:9s} rho {rb:6.1f} n{n} {nodes:4s} E {E:7.1f} range {rg:5.1f} pred {Ep:7.1f} err {(E/Ep-1)*100:+5.1f}% vsopt {(E/opt-1)*100:+5.1f}%  T {Tm:6.0f} Tp {Tp:6.0f}")

print("\n--- LaTeX ladder (sorted by rho)")
lab=lambda t: {'opt':'optimum (30,25,0,0)','allfpga':'all-FPGA','allcpu':'all-CPU'}.get(t, f"{t[:2].upper()}{t[2:4]} + {t[4:6].upper()}{t[6:8]}")
for rb,t,n,nodes,E,rg,Ep,Tm,Tp in sorted([r for r in rows if r[0]],key=lambda r:-r[0]):
    print(f"{lab(t)} & {rb:.1f} & {E:.1f} & {Ep:.1f} & {(E/opt-1)*100:+.1f}\\% \\\\")
for t in ('allfpga','allcpu'):
    r=[x for x in rows if x[1]==t][0]; print(f"{lab(t)} & --- & {r[4]:.1f} & {r[6]:.1f} & {(r[4]/opt-1)*100:+.1f}\\% \\\\")
print("\n--- S1 (no interference)")
out=[]
for rb,t,n,nodes,E,rg,Ep,Tm,Tp in rows:
    x=alloc(t); T0,E0=S.sim(x,N,W,W,714.8,False)
    out.append(((Tm/T0-1)*100,t,T0,Tm,E0,E))
for eT,t,T0,Tm,E0,E in sorted(out,key=lambda r:(r[1] not in('allcpu','allfpga','opt'),r[0])):
    print(f"{lab(t):22s} & {T0:.0f} & {Tm:.0f} & ${(Tm/T0-1)*100:+.1f}\\%$ & {E0:.0f} & {E:.0f} & ${(E/E0-1)*100:+.1f}\\%$ \\\\")
