import itertools, sim as S
W=['QP','NB','DE','IM']
tF={w:S.par[w][0] for w in W}; EF={w:S.par[w][2] for w in W}
tC48={w:S.par[w][1] for w in W}; EC48={w:S.par[w][3] for w in W}
tC29={'QP':88.55,'NB':91.33,'DE':51.99,'IM':30.02}; EC29={'QP':12188,'NB':16608,'DE':8726,'IM':7082}
def lin(tC,EC,Nw,ws):
    def f(c,P,tc):
        x=dict(zip(ws,c)); k=sum(1 for w in ws if x[w]>0)
        T=max(sum(x[w]*tF[w] for w in ws)+k*tc, sum((Nw-x[w])*tC[w] for w in ws))
        return T,(P*T+sum(x[w]*EF[w]+(Nw-x[w])*EC[w] for w in ws))/1e3
    return f
def shared(Nw,ws):
    def f(c,P,tc):
        S.tcfg=tc; x=dict(zip(ws,c)); return S.sim(x,{w:Nw for w in ws},ws,ws,P,True)
    return f
cases=[('no footprint (48 cores), K=4',lin(tC48,EC48,30,W),30,W),
       ('partitioned cores, K=4',lin(tC29,EC29,30,W),30,W),
       ('shared cores, K=4',shared(30,W),30,W),
       ('no footprint, K=3 (QP,DE,IM)',lin(tC48,EC48,30,['QP','DE','IM']),30,['QP','DE','IM']),
       ('partitioned, N=10',lin(tC29,EC29,10,W),10,W),
       ('shared, N=10',shared(10,W),10,W)]
for name,f,Nw,ws in cases:
    pts=list(itertools.product(range(Nw+1),repeat=len(ws)))
    for P in (714.8,300,200,100):
        vals=[(c,)+tuple(f(c,P,5.9)) for c in pts]
        opt=min(vals,key=lambda v:v[2])
        nor=min(pts,key=lambda c:f(c,P,0.0)[1])
        Enor=f(nor,P,5.9)[1]
        print(f"{name:32s} P={P:5.1f} opt {opt[0]} {opt[2]:7.1f} | no-reconf opt {nor} -> {Enor:7.1f} ({(Enor/opt[2]-1)*100:+.2f}%)")
