import sim as S
W4=['QP','NB','DE','IM']
def simt(x,N,P,interf,t):
    S.tcfg=t; return S.sim(x,N,W4,W4,P,interf)
tF={'QP':45.17,'NB':44.53,'DE':60.11,'IM':61.31}; EF={'QP':211,'NB':4343,'DE':532,'IM':439}
tC29={'QP':88.55,'NB':91.33,'DE':51.99,'IM':30.02}; EC29={'QP':12188,'NB':16608,'DE':8726,'IM':7082}
def static(x,N,P,t):
    c=sum(1 for w in N if x.get(w,0)>0)
    TF=sum(x.get(w,0)*tF[w] for w in N)+c*t; TC=sum((N[w]-x.get(w,0))*tC29[w] for w in N)
    T=max(TF,TC); return T,(P*T+sum(x.get(w,0)*EF[w]+(N[w]-x.get(w,0))*EC29[w] for w in N))/1e3
def sharedfp(x,N,P,t):
    par=S.par; c={'QP':1,'NB':19,'DE':3,'IM':1}
    k=sum(1 for w in N if x.get(w,0)>0)
    TF=sum(x.get(w,0)*par[w][0] for w in N)+k*t
    TC=sum((N[w]-x.get(w,0))*par[w][1] for w in N)+sum(x.get(w,0)*c[w]*par[w][0]/48 for w in N)
    T=max(TF,TC); return T,(P*T+sum(x.get(w,0)*par[w][2]+(N[w]-x.get(w,0))*par[w][3] for w in N))/1e3
def show(name,f,args,ref):
    a=f(*args,5.4); b=f(*args,5.9)
    print(f"{name:28} tab {ref}  calc5.4 ({a[0]:.1f},{a[1]:.1f})  new5.9 ({b[0]:.1f},{b[1]:.1f})  dT {b[0]-a[0]:+.1f} dE {b[1]-a[1]:+.2f}")
N3={'QP':30,'NB':0,'DE':30,'IM':30}; N4={w:30 for w in W4}
print("== A (P 708.3)")
for x,ref in (({'QP':30,'DE':3},'iso 1571.6/1558.5'),({'QP':30,'DE':4},'iso 1606.3/1574.8')):
    show(str(x)+' iso',lambda x,N,P,t: simt(x,N,P,False,t),(x,N3,708.3),ref)
for x,ref in (({'QP':30,'DE':3},'mat 1629.1/1599.2'),({'QP':30,'DE':4},'mat 1606.3/1574.8'),({'QP':30,'IM':4},'mat 1645.4/1610.6')):
    show(str(x)+' mat',lambda x,N,P,t: simt(x,N,P,True,t),(x,N3,708.3),ref)
print("== B regimes (P 714.8)")
show('shared (30,25)',lambda x,N,P,t: simt(x,N,P,True,t),({'QP':30,'NB':25},N4,714.8),'2518.6/2458.4')
for x,ref in (({'QP':28,'NB':30},'2637.4/2520.5'),({'QP':30,'NB':25},'2916.9/2757.8'),({'QP':26,'NB':30,'DE':2},'2710.5/2580.4')):
    show('static '+str(x),static,(x,N4,714.8),ref)
print("== ladder E pred (P 714.8)")
lad=[('NB30+QP21',{'QP':21,'NB':30},2657.3),('QP30+NB21',{'QP':30,'NB':21},2679.3),('QP30+DE21',{'QP':30,'DE':21},2969.4),
('QP30+IM21',{'QP':30,'IM':21},3374.6),('NB30+DE21',{'NB':30,'DE':21},3448.9),('DE30+IM21',{'DE':30,'IM':21},3662.2),
('allFPGA',{w:30 for w in W4},4708.4),('allCPU',{},4874.3)]
for n,x,r in lad: show(n,lambda x,N,P,t: simt(x,N,P,True,t),(x,N4,714.8),r)
print("== mvm iso (P 714.8)")
for n,x,r in [('opt',{'QP':30,'NB':25},'2479/2430')]+[(n,x,'') for n,x,_ in lad]: show(n+' iso',lambda x,N,P,t: simt(x,N,P,False,t),(x,N4,714.8),r)
print("== C (P 729.7)")
for xn,ri,rm,rs in ((21,2383.3,2720.5,2590.2),(23,2425.2,2608.2,2511.4),(25,2467.1,2495.9,2467.1),(27,2509.0,2509.0,2509.0)):
    x={'QP':30,'NB':xn}
    show(f'C x={xn} iso',lambda x,N,P,t: simt(x,N,P,False,t),(x,N4,729.7),ri)
    show(f'C x={xn} mat',lambda x,N,P,t: simt(x,N,P,True,t),(x,N4,729.7),rm)
    show(f'C x={xn} shared',sharedfp,(x,N4,729.7),rs)
print("== D static (P 728.6)")
for xn,r in ((25,'2916.9/2797.5'),(27,'2734.3/2639.9'),(29,'2657.3/2559.2'),(30,'2701.8/2579.4')):
    show(f'D x={xn}',static,({'QP':30,'NB':xn},N4,728.6),r)

print("== ladder exact")
for n,x,r in lad:
    a=simt(x,N4,714.8,True,5.4)[1]; b=simt(x,N4,714.8,True,5.9)[1]; print(n, f"{a:.2f} -> {b:.2f}")
print("== mvm exact (T,E int)")
meas={'opt':(2511,2487),'NB30+QP21':(2794,2744),'QP30+NB21':(2890,2797),'QP30+DE21':(3156,3115),'QP30+IM21':(3698,3517),'NB30+DE21':(3843,3591),'DE30+IM21':(3963,3785),'allFPGA':(6350,4705),'allCPU':(5072,4955)}
for n,x in [('opt',{'QP':30,'NB':25})]+[(n,x) for n,x,_ in lad]:
    T,E=simt(x,N4,714.8,False,5.9); Tm,Em=meas[n]
    print(f"{n:10} T {T:.1f}->{round(T)} E {E:.1f}->{round(E)}  errT {(Tm/round(T)-1)*100:+.1f}% errE {(Em/round(E)-1)*100:+.1f}%")
