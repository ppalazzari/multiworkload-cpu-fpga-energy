par={'QP':(45.17,55.22,211,11683),'NB':(44.53,55.74,4343,15885),'DE':(60.11,37.62,532,8792),'IM':(61.31,18.53,439,6665)}
S={'QP':{'QP':1.0,'NB':9.5,'DE':1.0,'IM':1.0},'NB':{'QP':1.381,'NB':1.744,'DE':1.157,'IM':1.346},
   'DE':{'QP':1.006,'NB':1.705,'DE':1.006,'IM':1.008},'IM':{'QP':1.064,'NB':1.656,'DE':1.208,'IM':1.064}}
tcfg=5.4
def sim(x,N,fpga_order,cpu_order,P,interf=True):
    # FPGA timeline (m=1)
    segs=[];t=0
    for w in fpga_order:
        if x.get(w,0)>0:
            t+=tcfg; d=x[w]*par[w][0]; segs.append((t,t+d,w)); t+=d
    TF=t
    # CPU progress
    tc=0
    for u in cpu_order:
        n=N[u]-x.get(u,0)
        if n<=0: continue
        rem=n
        while rem>1e-9:
            # current FPGA workload at time tc
            v=None; nxt=float('inf')
            for a,b,w in segs:
                if a<=tc<b: v=w; nxt=b; break
                if a>tc: nxt=min(nxt,a); break
            s=S[u][v] if (interf and v) else 1.0
            rate=1/(par[u][1]*s)
            dt=min(rem/rate, nxt-tc)
            rem-=rate*dt; tc+=dt
    T=max(TF,tc)
    Eapp=sum(x.get(w,0)*par[w][2]+(N[w]-x.get(w,0))*par[w][3] for w in N)
    return T,(P*T+Eapp)/1e3
