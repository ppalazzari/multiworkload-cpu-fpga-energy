import itertools, sim as S
S.tcfg=5.9
W=['QP','NB','DE','IM']; N={w:30 for w in W}
tF={w:S.par[w][0] for w in W}; EF={w:S.par[w][2] for w in W}
tC29={'QP':88.55,'NB':91.33,'DE':51.99,'IM':30.02}; EC29={'QP':12188,'NB':16608,'DE':8726,'IM':7082}
pts=list(itertools.product(range(31),repeat=4))
# precompute T and Eapp so P-sweep is cheap
def pre_stat():
    out=[]
    for c in pts:
        x=dict(zip(W,c)); k=sum(1 for w in W if x[w]>0)
        TF=sum(x[w]*tF[w] for w in W)+k*5.9; TC=sum((30-x[w])*tC29[w] for w in W)
        out.append((c,max(TF,TC),sum(x[w]*EF[w]+(30-x[w])*EC29[w] for w in W)))
    return out
def pre_sh():
    out=[]
    for c in pts:
        x=dict(zip(W,c)); T,E=S.sim(x,N,W,W,0,True)
        out.append((c,T,E*1e3))
    return out
for name,pre in (('static',pre_stat()),('shared',pre_sh())):
    print(name)
    for P in (0,100,200,300,400,500,600,714.8,900,1200,1500,2000):
        best=min(pre,key=lambda r:P*r[1]+r[2]); tb=min(pre,key=lambda r:(r[1],P*r[1]+r[2]))
        print(f"  P={P:6.1f} Eopt {best[0]} E={(P*best[1]+best[2])/1e3:7.1f} T={best[1]:7.1f} | Topt {tb[0]} E={(P*tb[1]+tb[2])/1e3:7.1f} (+{((P*tb[1]+tb[2])/(P*best[1]+best[2])-1)*100:.1f}%)")
# iso-balanced allocation evaluated under interference
x={'QP':20,'NB':30,'DE':0,'IM':0}
print('iso choice (20,30) under interference', [round(a,1) for a in S.sim(x,N,W,W,714.8,True)])
