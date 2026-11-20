import itertools, math
P=48; Pid=712.0; tcfg=5.4; N=30
c={'QP':1,'NB':19,'DE':3,'IM':1}
tF={'QP':45.19,'NB':44.54,'DE':59.14,'IM':60.08}
EF={'QP':325,'NB':3608,'DE':834,'IM':607}
EC={'QP':14072,'NB':15533,'DE':8269,'IM':7645}
def tC(w,p):
    if w=='QP': return 59.71*9/max(1,min(9,p//5))
    if w=='DE': return 37.64*40/min(40,p)
    if w=='IM': return 18.55*48/p
    if w=='NB': return 55.54*48/p
W=list(c)
def evalx(x):
    S=[w for w in W if x[w]>0]; cS=max([c[w] for w in S],default=0); p=P-cS
    TF=sum(x[w]*tF[w] for w in W)+len(S)*tcfg
    TC=sum((N-x[w])*tC(w,p) for w in W)
    T=max(TF,TC); E=sum(x[w]*EF[w]+(N-x[w])*EC[w] for w in W)+Pid*T
    return E,T,TF,TC,p
best=[];
for combo in itertools.product(range(N+1),repeat=4):
    x=dict(zip(W,combo)); E,T,TF,TC,p=evalx(x); best.append((E,T,combo,p,TF,TC))
best.sort()
for b in best[:5]: print([round(b[0]/1e3,1),round(b[1]),b[2],'p=',b[3],round(b[4]),round(b[5])])
# best per support
from collections import defaultdict
bs={}
for b in best:
    S=tuple(w for w,xx in zip(W,b[2]) if xx>0)
    if S not in bs: bs[S]=b
for S,b in sorted(bs.items(), key=lambda kv: kv[1][0])[:8]: print(S, round(b[0]/1e3,1), round(b[1]), b[2], 'p=',b[3])
for x in [(30,21,0,0),(30,25,0,0),(30,0,0,0)]:
    E,T,TF,TC,p=evalx(dict(zip(W,x))); print(x, round(E/1e3,1), round(T), p)
# densities per support
for S in [('QP',),('QP','NB'),('QP','DE')]:
    cS=max(c[w] for w in S); p=P-cS
    print(S,'p',p,{w: round(((EC[w]-EF[w])+Pid*tC(w,p))/(tF[w]+tC(w,p)),1) for w in W})
print("---- B: ripartizione dinamica (core-secondi)")
tC48={'QP':59.71,'NB':55.54,'DE':37.64,'IM':18.55}
def evalB(x):
    S=[w for w in W if x[w]>0]
    TF=sum(x[w]*tF[w] for w in W)+len(S)*tcfg
    TC=sum((N-x[w])*tC48[w] for w in W)+sum(x[w]*tF[w]*c[w]/P for w in W)
    T=max(TF,TC); E=sum(x[w]*EF[w]+(N-x[w])*EC[w] for w in W)+Pid*T
    return E,T,TF,TC
bb=min(((evalB(dict(zip(W,cmb)))[0],cmb) for cmb in itertools.product(range(N+1),repeat=4)))
E,T,TF,TC=evalB(dict(zip(W,bb[1]))); print(bb[1], round(E/1e3,1), round(T), round(TF), round(TC))
print({w: round(((EC[w]-EF[w])+Pid*(tC48[w]-c[w]*tF[w]/P))/(tF[w]+tC48[w]-c[w]*tF[w]/P),1) for w in W})
