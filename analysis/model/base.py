import itertools, sim as S
S.tcfg=5.9
W=['QP','NB','DE','IM']; N={w:30 for w in W}; P=714.8
tF={w:S.par[w][0] for w in W}; EF={w:S.par[w][2] for w in W}
tC29={'QP':88.55,'NB':91.33,'DE':51.99,'IM':30.02}; EC29={'QP':12188,'NB':16608,'DE':8726,'IM':7082}
def stat(x,P=P):
    c=sum(1 for w in W if x[w]>0)
    TF=sum(x[w]*tF[w] for w in W)+c*5.9; TC=sum((30-x[w])*tC29[w] for w in W)
    T=max(TF,TC); return T,(P*T+sum(x[w]*EF[w]+(30-x[w])*EC29[w] for w in W))/1e3
def shared(x,P=P): return S.sim(x,N,W,W,P,True)
import sys
res={}
for name,f in (('static',stat),('shared',shared)):
    pts=[dict(zip(W,c)) for c in itertools.product(range(31),repeat=4)]
    vals=[(f(x),x) for x in pts]
    eo=min(vals,key=lambda v:(v[0][1],v[0][0])); to=min(vals,key=lambda v:(v[0][0],v[0][1]))
    print(name,'E-opt',eo[1],[round(a,1) for a in eo[0]],'T-opt',to[1],[round(a,1) for a in to[0]],
          'extraE %.2f%%'%((to[0][1]/eo[0][1]-1)*100),'T saving %.1f%%'%((1-to[0][0]/eo[0][0])*100))
    # ties in T: all allocations within 0.1% of min T, pick min/max E
    Tmin=to[0][0]; near=[v for v in vals if v[0][0]<=Tmin*1.001]
    print('  near-T-opt count',len(near),'E range',round(min(v[0][1] for v in near),1),round(max(v[0][1] for v in near),1))
    for x in ({'QP':17,'NB':17,'DE':12,'IM':7},{'QP':30,'NB':25,'DE':0,'IM':0},{'QP':28,'NB':30,'DE':0,'IM':0},{w:0 for w in W},{w:30 for w in W}):
        print('  ',x,[round(a,1) for a in f(x)])
