// THREAD living orb: the acoustic sphere, rendered live.
//
// Same identity as images/thread-sphere.png (dark glass body, bright rim, top-right highlight, luminous
// threads of sound), but driven by real state: the threads move with the measured voice level, twist while
// THREAD plans, flatten and ripple the instant it is interrupted, turn amber while a correction holds an
// action, and bloom a green ring only when an action returned a real receipt. Nothing here invents state;
// callers report what actually happened. WebGL with a Canvas2D fallback; honours prefers-reduced-motion and
// pauses while hidden.

const PRESETS = {
  idle:       { amp: .10, speed: .30, twist: 0,   energy: .48, col: [.36, .62, 1.0], rim: [.15, .45, .98] },
  connecting: { amp: .18, speed: .55, twist: .3,  energy: .58, col: [.42, .66, 1.0], rim: [.18, .48, .98] },
  listening:  { amp: .22, speed: .75, twist: 0,   energy: .86, col: [.50, .80, 1.0], rim: [.20, .56, 1.0] },
  hesitating: { amp: .15, speed: .42, twist: 0,   energy: .72, col: [.62, .85, 1.0], rim: [.22, .58, 1.0] },
  thinking:   { amp: .34, speed: 1.15, twist: 1,  energy: .92, col: [.68, .62, 1.0], rim: [.34, .43, 1.0] },
  working:    { amp: .28, speed: .95, twist: .45, energy: .92, col: [.52, .73, 1.0], rim: [.22, .50, 1.0] },
  speaking:   { amp: .36, speed: 1.35, twist: 0,  energy: 1.1, col: [.58, .86, 1.0], rim: [.26, .62, 1.0] },
  held:       { amp: .22, speed: .60, twist: 0,   energy: .92, col: [1.0, .76, .36], rim: [.96, .62, .22] },
  error:      { amp: .10, speed: .25, twist: 0,   energy: .60, col: [1.0, .52, .50], rim: [.86, .32, .30] },
  muted:      { amp: .06, speed: .18, twist: 0,   energy: .36, col: [.56, .61, .71], rim: [.36, .42, .52] },
};
const MOODS = {
  neutral:    { look: 0,   lookY: 0,    warm: 0,   energy: 1,   amp: 1 },
  curious:    { look: .32, lookY: .04,  warm: 0,   energy: 1.04, amp: 1.05 },
  focused:    { look: 0,   lookY: 0,    warm: 0,   energy: 1.1, amp: .82 },
  pleased:    { look: .08, lookY: .03,  warm: .55, energy: 1.08, amp: 1.05 },
  apologetic: { look: -.1, lookY: -.12, warm: 0,   energy: .76, amp: .8 },
};
const FLASH = { done: [.36, .94, .55], error: [1.0, .42, .40], correction: [1.0, .74, .30] };

const VERTEX = `attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}`;
const FRAGMENT = `precision highp float;
uniform vec2 u_res;uniform float u_time,u_level,u_amp,u_speed,u_twist,u_energy,u_ripple,u_flash,u_duck,u_warm,u_dark,u_scale;
uniform vec3 u_col,u_rim,u_flashCol;uniform vec2 u_look;
float ribbon(vec2 q,float A,float f,float ph,float w,float bend){
  float env=pow(max(cos(q.x*1.5707963),0.),.9);
  float y=A*env*sin(f*q.x+ph)+bend*env*q.x*.15;
  float d=abs(q.y-y);
  return exp(-(d*d)/(w*w))+exp(-d/(w*5.))*.22;
}
void main(){
  float m=min(u_res.x,u_res.y);
  vec2 uv=(gl_FragCoord.xy-.5*u_res)/(.5*m)/u_scale;
  float R=.78*(1.-.07*u_duck);
  float r=length(uv);
  float px=3./(m*u_scale);
  float inside=1.-smoothstep(R-px,R+px,r);
  float n=clamp(r/R,0.,1.);
  vec3 body=vec3(.012,.034,.105);
  body+=u_rim*.62*pow(n,2.6);
  body+=u_rim*.30*smoothstep(.25,-.95,uv.y)*(1.-n*.25);
  float neb=sin(uv.x*2.6+u_time*.17)*sin(uv.y*3.4-u_time*.13)+sin((uv.x+uv.y)*4.1+u_time*.11);
  body+=u_rim*.045*(neb+1.5)*(1.-n*.5);
  vec2 q=uv/R;
  float tw=u_twist*.55*sin(u_time*.9);
  float c=cos(tw),s=sin(tw);
  q=vec2(c*q.x-s*q.y,s*q.x+c*q.y);
  float A=(.20+.30*u_amp+.55*u_level)*(1.-.85*u_duck);
  float t=u_time*u_speed;
  float th=ribbon(q+vec2(0.,.04),A,2.8,t,.016,0.);
  th+=ribbon(q+vec2(0.,-.06),A*.85,2.1,-t*.72+1.9,.012,.5)*.85;
  th+=ribbon(q,A*.70,3.9,t*1.27+3.3+u_twist*1.6*sin(t*.6),.011,-.4)*.75;
  th+=ribbon(q+vec2(0.,.22-u_look.y),A*1.45,1.25,-t*.38+4.6,.018,.9)*.55;
  th*=inside*(.62+.7*u_energy)*smoothstep(1.,.80,length(q));
  vec3 thread=mix(u_col,vec3(1.),.38)*th;
  float rim1=exp(-pow((r-R)/(px*1.5),2.));
  float rim2=exp(-pow((r-(R-.03))/(px*2.),2.))*.30;
  float ang=atan(uv.y,uv.x);
  float da=ang-(.80+u_look.x);da=mod(da+3.14159265,6.2831853)-3.14159265;
  float hl=exp(-da*da/.13)*exp(-pow((r-(R-.02))/.045,2.))*1.15;
  float ring=0.;
  if(u_ripple<1.){float rr=R*(.15+u_ripple*1.05);ring=exp(-pow((r-rr)/.025,2.))*(1.-u_ripple)*inside;}
  float fring=0.;
  if(u_flash<1.3){float fr=R*(.2+u_flash*.95);fring=exp(-pow((r-fr)/.04,2.))*(1.-u_flash/1.3);}
  vec3 color=body*inside+thread;
  color+=u_rim*rim1*1.25*(.7+.5*u_energy)+u_rim*rim2;
  color+=vec3(.86,.94,1.)*hl*(.85+.3*u_energy);
  color+=vec3(.95,.98,1.)*ring*.9;
  color+=u_flashCol*fring*1.1*inside;
  color=mix(color,color*vec3(1.18,1.,.82)+vec3(.04,.02,0.),u_warm*inside);
  float a=max(inside,rim1);
  float out_=max(r-R,0.);
  float halo=exp(-out_*mix(11.,7.5,u_dark))*(1.-inside)*(.30+.35*u_energy+.4*u_level);
  vec2 sp=uv-vec2(0.,-R*.10);
  float sh=exp(-max(length(sp*vec2(1.,1.35))-R*.88,0.)*5.)*(1.-inside)*.22;
  color+=u_rim*halo*mix(.45,1.,u_dark)+u_flashCol*fring*(1.-inside)*.6;
  a=clamp(a+halo*mix(.38,.9,u_dark)+fring*(1.-inside)*.6+sh*(1.-u_dark),0.,1.);
  gl_FragColor=vec4(color,a);
}`;

const lerp = (a, b, k) => a + (b - a) * k;
const ease = (dt, tau) => 1 - Math.exp(-dt / tau);

// 'auto' reads the nearest painted background behind the canvas: halo on dark stages, soft shadow on paper.
function backgroundIsDark(element) {
  for (let node = element; node && node !== document.documentElement; node = node.parentElement) {
    const match = getComputedStyle(node).backgroundColor.match(/rgba?\(([^)]+)\)/);
    if (!match) continue;
    const [r, g, b, a = 1] = match[1].split(',').map(Number);
    if (a > .05) return (.2126 * r + .7152 * g + .0722 * b) / 255 < .45;
  }
  return matchMedia('(prefers-color-scheme: dark)').matches;
}

export function createOrb(canvas, { theme = 'auto', image = null, scale = 1 } = {}) {
  if (theme === 'auto') theme = backgroundIsDark(canvas) ? 'dark' : 'light';
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const target = { phase: 'idle', mood: 'neutral', level: 0 };
  const cur = { amp: .1, speed: .3, twist: 0, energy: .48, col: [...PRESETS.idle.col], rim: [...PRESETS.idle.rim],
    level: 0, look: 0, lookY: 0, warm: 0, duck: 0 };
  let time = 0, last = performance.now(), ripple = 9, flash = 9, flashCol = FLASH.done, raf = 0, visible = true;
  let gl = null, prog = null, loc = {}, fallback = null;

  try {
    gl = canvas.getContext('webgl', { premultipliedAlpha: true, antialias: true, alpha: true });
    const shader = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
    prog = gl.createProgram();
    gl.attachShader(prog, shader(gl.VERTEX_SHADER, VERTEX)); gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, FRAGMENT));
    gl.linkProgram(prog); if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    gl.useProgram(prog);
    const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const p = gl.getAttribLocation(prog, 'p'); gl.enableVertexAttribArray(p); gl.vertexAttribPointer(p, 2, gl.FLOAT, false, 0, 0);
    for (const name of ['u_res', 'u_time', 'u_level', 'u_amp', 'u_speed', 'u_twist', 'u_energy', 'u_ripple', 'u_flash', 'u_duck',
      'u_warm', 'u_dark', 'u_scale', 'u_col', 'u_rim', 'u_flashCol', 'u_look']) loc[name] = gl.getUniformLocation(prog, name);
    gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
  } catch (error) {
    gl = null; fallback = canvas.getContext('2d');
    if (image) { fallback.img = new Image(); fallback.img.src = image; }
  }

  const io = 'IntersectionObserver' in window ? new IntersectionObserver(([e]) => { visible = e.isIntersecting; }) : null;
  io?.observe(canvas);

  function step(now) {
    raf = requestAnimationFrame(step);
    const dt = Math.min((now - last) / 1000, .1); last = now;
    if (document.hidden || !visible) return;
    const still = reduced.matches;
    const pre = PRESETS[target.phase] || PRESETS.idle, mood = MOODS[target.mood] || MOODS.neutral;
    const kc = ease(dt, .35), kf = ease(dt, .18);
    cur.amp = lerp(cur.amp, pre.amp * mood.amp, kf); cur.speed = lerp(cur.speed, still ? 0 : pre.speed, kc);
    cur.twist = lerp(cur.twist, still ? 0 : pre.twist, kc); cur.energy = lerp(cur.energy, pre.energy * mood.energy, kc);
    for (let i = 0; i < 3; i++) { cur.col[i] = lerp(cur.col[i], pre.col[i], kc); cur.rim[i] = lerp(cur.rim[i], pre.rim[i], kc); }
    // Fast attack, slower release, so the threads follow speech without jitter.
    const lv = still ? target.level * .25 : target.level;
    cur.level = lerp(cur.level, lv, ease(dt, lv > cur.level ? .05 : .16));
    const lookTarget = mood.look * (target.mood === 'curious' && !still ? Math.sin(time * .7) : 1);
    cur.look = lerp(cur.look, lookTarget, kc); cur.lookY = lerp(cur.lookY, mood.lookY, kc); cur.warm = lerp(cur.warm, mood.warm, kc);
    cur.duck = Math.max(0, cur.duck - dt * 2.6);
    time += dt; ripple += dt * 1.6; flash += dt;
    const rect = canvas.getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(rect.width * dpr)), h = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    if (gl) {
      gl.viewport(0, 0, w, h); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform2f(loc.u_res, w, h); gl.uniform1f(loc.u_time, time); gl.uniform1f(loc.u_level, cur.level);
      gl.uniform1f(loc.u_amp, cur.amp); gl.uniform1f(loc.u_speed, cur.speed); gl.uniform1f(loc.u_twist, cur.twist);
      gl.uniform1f(loc.u_energy, cur.energy); gl.uniform1f(loc.u_ripple, still ? 9 : ripple); gl.uniform1f(loc.u_flash, flash);
      gl.uniform1f(loc.u_duck, still ? 0 : cur.duck); gl.uniform1f(loc.u_warm, cur.warm); gl.uniform1f(loc.u_dark, theme === 'dark' ? 1 : 0);
      gl.uniform1f(loc.u_scale, scale); gl.uniform3fv(loc.u_col, cur.col); gl.uniform3fv(loc.u_rim, cur.rim);
      gl.uniform3fv(loc.u_flashCol, flashCol); gl.uniform2f(loc.u_look, cur.look, cur.lookY);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    } else if (fallback) {
      const ctx = fallback; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, rect.width, rect.height);
      const side = Math.min(rect.width, rect.height) * scale * (1 + cur.level * .045) * (1 - cur.duck * .06);
      ctx.save(); ctx.translate(rect.width / 2, rect.height / 2);
      if (ctx.img?.complete && ctx.img.naturalWidth) ctx.drawImage(ctx.img, -side / 2, -side / 2, side, side);
      const [r, g, b] = cur.rim.map(v => Math.round(v * 255));
      ctx.strokeStyle = `rgba(${r},${g},${b},.55)`; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(0, 0, side * .39, 0, Math.PI * 2); ctx.stroke(); ctx.restore();
    }
  }
  raf = requestAnimationFrame(step);

  return {
    get phase() { return target.phase; },
    setPhase(name) { if (PRESETS[name]) target.phase = name; },
    setMood(name) { if (MOODS[name]) target.mood = name; },
    setLevel(value) { target.level = Math.max(0, Math.min(1, Number(value) || 0)); },
    // 'interrupt': instant duck + ripple. 'done' / 'error' / 'correction': a ring for a real receipt, failure or
    // controller withdrawal of superseded work.
    pulse(kind) {
      if (kind === 'interrupt') { ripple = 0; cur.duck = 1; }
      else if (FLASH[kind]) { flash = 0; flashCol = FLASH[kind]; }
    },
    setTheme(name) { theme = name; },
    destroy() { cancelAnimationFrame(raf); io?.disconnect(); },
  };
}

export const ORB_PHASES = Object.keys(PRESETS);
export const ORB_MOODS = Object.keys(MOODS);
