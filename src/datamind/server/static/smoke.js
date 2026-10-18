'use strict';

// Smoke: hashed value noise, six-octave fbm, and two levels of domain warp.
// The background is computed entirely in WebGL1; no textures or image assets.
function initSmoke() {
  const canvas = document.getElementById('smokeCanvas');
  const fallback = document.getElementById('shaderFallback');
  const gl = canvas.getContext('webgl', {
    alpha: false, antialias: false, depth: false, stencil: false,
    premultipliedAlpha: false, powerPreference: 'low-power',
  });
  const showFallback = () => { fallback.hidden = false; canvas.classList.remove('ready'); };
  if (!gl) { showFallback(); return; }

  const vertex = `
attribute vec2 a_position;
void main() { gl_Position = vec4(a_position, 0.0, 1.0); }
`;
  const fragment = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
uniform vec2 u_resolution;
uniform vec2 u_pointer;
uniform float u_time;
uniform float u_intensity;

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
             mix(hash(i + vec2(0.0, 1.0)), hash(i + 1.0), u.x), u.y);
}

float fbm(vec2 p) {
  float value = 0.0, amplitude = 0.5;
  mat2 turn = mat2(0.80, -0.60, 0.60, 0.80);
  for (int i = 0; i < 6; i++) {
    value += amplitude * noise(p);
    p = turn * p * 2.02 + vec2(13.1, 7.7);
    amplitude *= 0.5;
  }
  return value;
}

float domainWarp(vec2 p, float time, out vec2 q, out vec2 r) {
  q = vec2(fbm(p + vec2(0.0, time * 0.08)),
           fbm(p + vec2(5.2, 1.3) - time * 0.06));
  r = vec2(fbm(p + 4.0 * q + vec2(1.7, 9.2) + time * 0.12),
           fbm(p + 4.0 * q + vec2(8.3, 2.8) - time * 0.10));
  return fbm(p + 4.3 * r);
}

void main() {
  vec2 uv = gl_FragCoord.xy / u_resolution;
  float aspect = u_resolution.x / u_resolution.y;
  vec2 p = (uv - 0.5) * vec2(aspect, 1.0) * 2.65;
  p += vec2(1.8, -0.4);

  vec2 pointerDelta = (uv - u_pointer) * vec2(aspect, 1.0);
  float presence = exp(-dot(pointerDelta, pointerDelta) * 5.0) * u_intensity;
  p += presence * 0.14 * vec2(sin(p.y * 2.0), cos(p.x * 2.0));

  vec2 q, r;
  float field = domainWarp(p, u_time * 0.36, q, r);
  float crest = pow(smoothstep(0.28, 0.77, field), 3.2);
  float magnitude = length(r);
  float filament = pow(max(0.0, 1.0 - abs(magnitude - 0.73) * 13.0), 4.0);
  filament *= smoothstep(0.40, 0.70, field) * 0.34;
  float light = clamp(crest * 1.7 + filament, 0.0, 1.0);
  light *= 0.78 + presence * 0.42;

  const vec3 ground = vec3(0.003921569, 0.011764706, 0.050980392);
  const vec3 depth = vec3(0.003921569, 0.039215686, 0.125490196);
  const vec3 blue = vec3(0.298039216, 0.478431373, 0.980392157);
  vec3 color = mix(ground, depth, smoothstep(0.16, 0.64, field));
  color = mix(color, blue, clamp(light, 0.0, 1.0));
  // Leave a darker central reading zone, with the material cresting at the edge.
  float edgeLight = smoothstep(0.18, 0.95, uv.x) * 0.56 + 0.44;
  color = mix(ground, color, edgeLight);
  float vignette = 1.0 - 0.45 * smoothstep(0.25, 0.86, length(uv - 0.5));
  gl_FragColor = vec4(mix(ground, color, vignette), 1.0);
}
`;

  let program, positionBuffer;
  let uniforms = {};
  const compile = (type, source) => {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source); gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      const error = gl.getShaderInfoLog(shader); gl.deleteShader(shader); throw new Error(error);
    }
    return shader;
  };
  const build = () => {
    const vs = compile(gl.VERTEX_SHADER, vertex), fs = compile(gl.FRAGMENT_SHADER, fragment);
    program = gl.createProgram(); gl.attachShader(program, vs); gl.attachShader(program, fs); gl.linkProgram(program);
    gl.deleteShader(vs); gl.deleteShader(fs);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
    gl.useProgram(program);
    positionBuffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, 'a_position');
    gl.enableVertexAttribArray(position); gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
    uniforms = Object.fromEntries(['u_resolution', 'u_pointer', 'u_time', 'u_intensity'].map((name) => [name, gl.getUniformLocation(program, name)]));
    fallback.hidden = true; canvas.classList.add('ready');
  };

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let frame = null, lastTime = 0, elapsed = 12.0, previousRender = 0;
  let intensity = 0, targetIntensity = 0, pointerIdle = null, lost = false;
  const pointer = { x: 0.7, y: 0.5, targetX: 0.7, targetY: 0.5 };

  const resize = () => {
    const ratio = Math.min(window.devicePixelRatio || 1, 1.5, Math.sqrt(1600000 / (innerWidth * innerHeight)));
    canvas.width = Math.max(1, Math.round(innerWidth * ratio));
    canvas.height = Math.max(1, Math.round(innerHeight * ratio));
    gl.viewport(0, 0, canvas.width, canvas.height);
  };
  const render = () => {
    gl.uniform2f(uniforms.u_resolution, canvas.width, canvas.height);
    gl.uniform2f(uniforms.u_pointer, pointer.x, pointer.y);
    gl.uniform1f(uniforms.u_time, elapsed);
    gl.uniform1f(uniforms.u_intensity, intensity);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  };
  const tick = (now) => {
    frame = null;
    if (document.hidden || lost || reduced.matches) return;
    if (now - previousRender >= 32) {
      const dt = Math.min((now - (lastTime || now)) / 1000, 0.08);
      lastTime = now; previousRender = now; elapsed += dt;
      intensity += (targetIntensity - intensity) * (1 - Math.exp(-dt * (targetIntensity > intensity ? 4.5 : 1.8)));
      const ease = 1 - Math.exp(-dt * 6);
      pointer.x += (pointer.targetX - pointer.x) * ease; pointer.y += (pointer.targetY - pointer.y) * ease;
      render();
    }
    frame = requestAnimationFrame(tick);
  };
  const sync = () => {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null; lastTime = 0;
    if (document.hidden || lost) return;
    if (reduced.matches) { intensity = 0; render(); }
    else frame = requestAnimationFrame(tick);
  };
  const trackPointer = (event) => {
    if (reduced.matches || event.pointerType === 'touch') return;
    pointer.targetX = event.clientX / innerWidth; pointer.targetY = 1 - event.clientY / innerHeight;
    targetIntensity = 1;
    clearTimeout(pointerIdle); pointerIdle = setTimeout(() => { targetIntensity = 0; }, 250);
  };
  window.addEventListener('pointermove', trackPointer, { passive: true });
  document.documentElement.addEventListener('pointerleave', () => { targetIntensity = 0; });
  window.addEventListener('blur', () => { targetIntensity = 0; });
  window.addEventListener('resize', () => { if (!lost) { resize(); if (reduced.matches) render(); } }, { passive: true });
  document.addEventListener('visibilitychange', sync);
  reduced.addEventListener('change', sync);
  canvas.addEventListener('webglcontextlost', (event) => {
    event.preventDefault(); lost = true; sync(); showFallback();
  });
  canvas.addEventListener('webglcontextrestored', () => {
    try { lost = false; build(); resize(); if (!reduced.matches) render(); sync(); }
    catch (error) { console.error('Could not restore Smoke:', error); showFallback(); }
  });
  try { build(); resize(); if (!reduced.matches) render(); sync(); }
  catch (error) { console.error('Could not initialize Smoke:', error); lost = true; showFallback(); }
}
