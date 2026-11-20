import itertools
Q=48; P=728.6; tcfg=11.0; N=30; m=2
c={'QP':1,'NB':19,'DE':3,'IM':1}
tF={'QP':45.17,'NB':44.53,'DE':59.19,'IM':60.04}
EF={'QP':325,'NB':3608,'DE':834,'IM':607}
EC={'QP':14072,'NB':15533,'DE':8269,'IM':7645}
t48={'QP':59.71,'NB':55.54,'DE':37.64,'IM':18.55}
order=['QP','NB','DE','IM']
def tC(w,p):
    if p<=0: return 1e9
    if w=='QP': k=min(9,p//5); return 1e9 if k==0 else 59.71*9/k*0.967
    if w=='DE': return 37.64*40/min(40,p)
    return t48[w]*48/p
def cards(x):
    # balanced split, both cards process workloads in order
    loads=[0.0]*m; 
    for w in order:
        q,r=divmod(x[w],m)
        for j in range(m): loads[j]+=q*tF[w]
        for _ in range(r):
            j=min(range(m),key=lambda j:loads[j]); loads[j]+=tF[w]
    return max(loads)
W=order
def ev(x,model):
    S=[w for w in W if x[w]>0]
    TF=cards(x)+len(S)*tcfg if S else 0
    if model=='stat':
        cS=m*max([c[w] for w in S],default=0) if S else 0
        p=Q-cS
        TC=sum((N-x[w])*tC(w,p) for w in W)
    elif model=='dyn':
        TC=sum((N-x[w])*t48[w] for w in W)+sum(x[w]*c[w]*tF[w]/Q for w in W)
    else:
        TC=sum((N-x[w])*t48[w] for w in W)
    T=max(TF,TC); E=sum(x[w]*EF[w]+(N-x[w])*EC[w] for w in W)+P*T
    return E,T,TF,TC
for model in ('none','dyn','stat'):
    res=sorted((ev(dict(zip(W,cb)),model)+(cb,) for cb in itertools.product(range(N+1),repeat=4)))
    print(model)
    for r in res[:4]: print('  ',r[4], 'E',round(r[0]/1e3,1),'T',round(r[1]),'TF',round(r[2]),'TC',round(r[3]))
    for cb in [(30,30,6,0),(30,0,30,30),(30,30,30,30),(0,0,0,0)]:
        r=ev(dict(zip(W,cb)),model); print('    ',cb,'E',round(r[0]/1e3,1),'T',round(r[1]))
