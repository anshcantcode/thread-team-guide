#version 330
uniform vec2 resolution;
uniform float time;
uniform int mode;
uniform float intensity;
uniform float layerAlpha;
uniform vec2 center;
uniform float scale;
uniform vec3 angles;
uniform sampler2D macroTex;
uniform sampler2D sphereTex;
uniform sampler2D screenTex;
out vec4 fragColor;

float hash(vec2 p) {return fract(sin(dot(p,vec2(12.9898,78.233)))*43758.5453);}
mat3 rx(float a){float c=cos(a),s=sin(a);return mat3(1,0,0,0,c,s,0,-s,c);}
mat3 ry(float a){float c=cos(a),s=sin(a);return mat3(c,0,-s,0,1,0,s,0,c);}
mat3 rz(float a){float c=cos(a),s=sin(a);return mat3(c,s,0,-s,c,0,0,0,1);}
float shape(vec3 p){
    vec2 q=abs(p.xy)-vec2(.83,1.995);
    float d=length(max(q,0.))+min(max(q.x,q.y),0.)-.20;
    vec2 w=vec2(d,abs(p.z)-.105);
    return min(max(w.x,w.y),0.)+length(max(w,0.))-.014;
}
vec3 normalAt(vec3 p){vec2 e=vec2(.001,0);return normalize(vec3(shape(p+e.xyy)-shape(p-e.xyy),shape(p+e.yxy)-shape(p-e.yxy),shape(p+e.yyx)-shape(p-e.yyx)));}
vec3 phone(vec2 p,vec3 bg){
    mat3 rot=rx(angles.x)*ry(angles.y)*rz(angles.z);
    vec3 ro=rot*vec3(-center*6./scale,8.);
    vec3 rd=rot*normalize(vec3(p*6./scale,-8.));
    // Bounding sphere keeps the expensive surface search off the empty frame.
    float b=dot(ro,rd),c=dot(ro,ro)-6.1,h=b*b-c;
    if(h<0.) return bg;
    float d=max(0.,-b-sqrt(h));
    vec3 q=vec3(0.);
    bool hit=false;
    for(int i=0;i<68;i++){
        q=ro+rd*d;float s=shape(q);
        if(s<.0009){hit=true;break;}
        d+=s;
        if(d>12.)break;
    }
    if(!hit)return bg;
    vec3 n=normalAt(q);
    vec3 nw=transpose(rot)*n;
    vec3 refl=reflect(rd,n);
    float key=pow(max(dot(n,normalize(rot*vec3(-3.,4.,6.))),0.),22.);
    float edge=pow(1.-max(dot(n,-rd),0.),3.);
    float strip=pow(max(0.,1.-abs(refl.x*.62+refl.z*.78-.11)),60.);
    vec3 col=vec3(.027,.034,.047)+key*.4+strip*.55+edge*vec3(.07,.19,.32);
    if(q.z>.11 && n.z>.75){
        vec2 uv=vec2(q.x/1.96+.5,q.y/4.245+.5);
        vec2 cr=abs(q.xy)-vec2(.84,1.98);
        float rounded=length(max(cr,0.))+min(max(cr.x,cr.y),0.)-.128;
        if(rounded<0.){
            col=texture(screenTex,uv).rgb;
            float reflection=pow(max(0.,1.-abs(q.x*.31+q.y*.21-.6+angles.y*.5)),32.);
            col+=reflection*.029;
            // The existing screenshot includes the phone status bar.
            float lens=length(q.xy-vec2(0.,2.054));
            col=mix(col,vec3(.003,.007,.012),1.-smoothstep(.027,.036,lens));
        }
    }
    return col;
}
void main(){
    vec2 uv=gl_FragCoord.xy/resolution;
    vec2 p=(gl_FragCoord.xy-resolution*.5)/resolution.y;
    vec3 bg=vec3(.022,.036,.055);
    bg+=vec3(.011,.021,.036)*exp(-length(p-vec2(.2,.28))*2.4);
    vec3 col=bg;
    if(mode==0){
        vec2 cover=vec2(1.);
        float aspect=resolution.x/resolution.y;
        if(aspect<1.7778)cover.x=aspect/1.7778;else cover.y=1.7778/aspect;
        vec2 q=(uv-.5)*cover/(1.05+time*.006)+.5;
        q+=vec2(.012*sin(time*.22),.007*cos(time*.28));
        q+=vec2(sin(q.y*8.+time*.37),cos(q.x*7.+time*.3))*.0018;
        col=texture(macroTex,q).rgb;
        col*=.64+.16*sin(time*.44);
        col*=1.-.32*smoothstep(.1,.7,length(uv-.5));
        col=mix(bg,col,intensity);
    }
    if(mode==1){
        vec2 q=(p-center)/scale;
        float a=.015*sin(time*.3);
        q=mat2(cos(a),-sin(a),sin(a),cos(a))*q;
        q*=1.+.012*sin(time*1.8);
        q+=vec2(sin(q.y*8.+time*.65),cos(q.x*6.+time*.6))*.0028;
        vec2 st=q+.5;
        vec4 orb=texture(sphereTex,st);
        float inside=step(0.,st.x)*step(st.x,1.)*step(0.,st.y)*step(st.y,1.);
        col+=vec3(.01,.045,.11)*exp(-dot(q,q)*5.)*intensity;
        float sheen=.92+.08*sin(time*.75+q.x*4.);
        col=mix(col,orb.rgb*sheen,orb.a*inside*intensity);
    }
    if(mode==2){
        vec2 q=p-center;
        float env=exp(-q.x*q.x*.65);
        for(int i=0;i<28;i++){
            float f=float(i)/27.;
            float y=.13*sin(q.x*3.1-time*.65+f*2.8)*env;
            y+=.09*sin(q.x*5.1+time*.38+f*1.9)*env;
            y+=(f-.5)*(.035+.34*exp(-q.x*q.x*2.));
            float dist=abs(q.y-y*scale);
            vec3 blue=mix(vec3(.03,.18,.58),vec3(.22,.64,1.),f);
            col+=blue*(.00037/(dist+.003)+.33*exp(-dist*dist/0.000003))*intensity;
        }
        col+=vec3(.00,.025,.08)*exp(-q.y*q.y*15.);
    }
    if(mode==3){
        col+=vec3(.00,.035,.11)*exp(-length(p-center+vec2(0.,.34))*4.);
        col=phone(p,col);
    }
    float grain=(hash(gl_FragCoord.xy+fract(time*.113)*173.)-.5)/520.;
    col+=grain;
    col*=1.-.16*pow(length(uv-.5),1.3);
    fragColor=vec4(clamp(col,0.,1.),layerAlpha);
}
