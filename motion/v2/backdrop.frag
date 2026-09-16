#version 330
uniform vec2 resolution;
uniform float time;
out vec4 color;
void main(){
 vec2 uv=gl_FragCoord.xy/resolution;
 vec2 p=(uv-.5)*vec2(resolution.x/resolution.y,1.);
 vec3 ink=vec3(.025,.043,.071);
 float light=exp(-length((p-vec2(.34,-.35))*vec2(.9,1.35))*3.5);
 ink+=vec3(.008,.045,.12)*light;
 float grain=fract(sin(dot(gl_FragCoord.xy,vec2(12.9898,78.233)))*43758.5453)-.5;
 color=vec4(ink+grain*.0025,1.);
}
