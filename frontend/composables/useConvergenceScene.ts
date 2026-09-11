import * as THREE from 'three'

/**
 * The convergence scene.
 *
 * Four channels flowing into one inbox, drawn as one THREE.Points of up to 60k
 * particles with one ShaderMaterial and one draw call. Positions are never
 * computed on the CPU: the vertex shader evaluates a cubic Bezier from the
 * particle's channel node to the core, so the per-frame JavaScript cost is a
 * handful of uniform writes regardless of particle count.
 *
 * There is no UnrealBloomPass and there must not be one. Full postprocessing
 * costs extra render targets for an effect a well-authored additive sprite
 * delivers at a fraction of the cost, and it is the first thing that collapses
 * on a mid-range Android -- which is much of this audience.
 */

export interface SceneNode {
  id: string
  label: string
  /** Where it sits in world space. */
  position: THREE.Vector3
  color: THREE.Color
}

export interface NodeScreenPosition {
  id: string
  label: string
  /** Viewport pixels, or null when the node is behind the camera. */
  x: number
  y: number
  visible: boolean
}

export interface ConvergenceScene {
  setProgress(progress: number): void
  setCameraZ(z: number): void
  renderOnce(): void
  start(): void
  stop(): void
  dispose(): void
  nodeScreenPositions(): NodeScreenPosition[]
}

/** Camera z at progress 0 and 1. The scene tightens as the page scrolls. */
/** Keep-out band at the viewport edge for a projected node label. */
const LABEL_MARGIN = 64

export const CAMERA_Z_START = 9.0
export const CAMERA_Z_END = 3.2

const VERTEX_SHADER = /* glsl */ `
uniform float uTime;
uniform float uProgress;
uniform float uSize;
uniform float uPixelRatio;
uniform vec3  uNodes[4];
uniform vec3  uColors[4];
uniform vec3  uAccent;

attribute float aChannel;
attribute float aPhase;
attribute float aSpeed;
attribute float aSpread;
// Per-particle path perturbation. Without it every particle in a channel
// evaluates the *identical* Bezier and the flow collapses into four thin
// ribbons -- the single most important attribute in this file.
attribute vec3  aJitter;

varying vec3  vColor;
varying float vAlpha;

// --- noise ---------------------------------------------------------------
// Ashima's simplex, trimmed. Used three times per vertex with different
// offsets to build a drifting displacement field. It is not true curl noise --
// that needs six more samples for the finite differences, and at 60k vertices
// the difference is invisible once the displacement decays to zero at arrival,
// while the cost is not.
vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

float snoise(vec3 v) {
  const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);

  vec3 i  = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);

  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);

  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;

  i = mod289(i);
  vec4 p = permute(permute(permute(
             i.z + vec4(0.0, i1.z, i2.z, 1.0))
           + i.y + vec4(0.0, i1.y, i2.y, 1.0))
           + i.x + vec4(0.0, i1.x, i2.x, 1.0));

  float n_ = 0.142857142857;
  vec3 ns = n_ * D.wyz - D.xzx;

  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);

  vec4 x = x_ * ns.x + ns.yyyy;
  vec4 y = y_ * ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);

  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);

  vec4 s0 = floor(b0) * 2.0 + 1.0;
  vec4 s1 = floor(b1) * 2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));

  vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;

  vec3 p0 = vec3(a0.xy, h.x);
  vec3 p1 = vec3(a0.zw, h.y);
  vec3 p2 = vec3(a1.xy, h.z);
  vec3 p3 = vec3(a1.zw, h.w);

  vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
  p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;

  vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
  m = m * m;
  return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
}

vec3 drift(vec3 p) {
  return vec3(
    snoise(p),
    snoise(p + vec3(31.416, 0.0, 17.0)),
    snoise(p + vec3(0.0, 71.5, 43.2))
  );
}

// --- path ----------------------------------------------------------------
vec3 bezier(vec3 a, vec3 b, vec3 c, vec3 d, float t) {
  float u = 1.0 - t;
  return u * u * u * a + 3.0 * u * u * t * b + 3.0 * u * t * t * c + t * t * t * d;
}

void main() {
  int channel = int(aChannel + 0.5);
  vec3 node = uNodes[channel];
  vec3 core = vec3(0.0);

  // Flow accelerates as the page scrolls. Never to zero at the top: a still
  // hero looks broken rather than calm.
  float speed = aSpeed * mix(0.6, 1.55, uProgress);
  float t = fract(uTime * speed + aPhase);

  // Each particle leaves from its own point in a cloud around the node, not
  // from the node itself, so the stream has width where it starts.
  vec3 origin = node + aJitter * aSpread * 2.4;

  // Control points bowed outward, so the paths arc rather than converge as
  // four straight spokes. The bow is per-particle, which is what turns one
  // curve into a braid of them, and it tightens with progress: convergence
  // reads as the paths themselves closing in, not just the camera moving.
  vec3 outward = normalize(vec3(-node.y, node.x, 0.6));
  vec3 bow = (outward * 1.35 + aJitter * 2.1) * mix(1.0, 0.35, uProgress);
  vec3 c1 = mix(origin, core, 0.32) + bow;
  vec3 c2 = mix(origin, core, 0.74) + bow * 0.3;

  vec3 position = bezier(origin, c1, c2, core, t);

  // Turbulent at the edges, clean at the centre: the displacement decays to
  // exactly zero at arrival, so the core stays a point rather than a smudge.
  float turbulence = aSpread * (1.0 - t) * (1.0 - t) * 0.9;
  position += drift(position * 0.42 + uTime * 0.05) * turbulence;

  vec4 viewPosition = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * viewPosition;

  // Colour convergence and spatial convergence are the same gesture: the hue
  // travels from the channel's own to the accent as the particle arrives. Held
  // late so each channel keeps its identity for most of its run.
  vColor = mix(uColors[channel], uAccent, smoothstep(0.55, 1.0, t));

  // Fade in from the node and out at the core, so particles are born and
  // absorbed rather than popping.
  vAlpha = smoothstep(0.0, 0.12, t) * (1.0 - smoothstep(0.82, 1.0, t)) * 0.55;

  gl_PointSize = uSize * uPixelRatio * (0.7 + t * 0.5) * (12.0 / -viewPosition.z);
}
`

const FRAGMENT_SHADER = /* glsl */ `
precision mediump float;

varying vec3  vColor;
varying float vAlpha;

void main() {
  // A soft radial falloff. Additive blending does the rest of the work an
  // expensive bloom pass would otherwise be doing.
  float d = length(gl_PointCoord - 0.5);
  float falloff = smoothstep(0.5, 0.0, d);
  falloff *= falloff;
  if (falloff < 0.01) discard;
  gl_FragColor = vec4(vColor, falloff * vAlpha);
}
`

const CORE_VERTEX = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`

const CORE_FRAGMENT = /* glsl */ `
precision mediump float;
uniform vec3  uAccent;
uniform float uIntensity;
varying vec2  vUv;

void main() {
  float d = length(vUv - 0.5) * 2.0;
  float glow = pow(max(0.0, 1.0 - d), 3.0);
  gl_FragColor = vec4(uAccent, glow * uIntensity);
}
`

function cssColor(name: string, fallback: string): THREE.Color {
  if (typeof window === 'undefined') return new THREE.Color(fallback)
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return new THREE.Color(value || fallback)
}

export interface SceneOptions {
  particles: number
  reducedMotion: boolean
}

export function useConvergenceScene(
  canvas: HTMLCanvasElement,
  options: SceneOptions,
): ConvergenceScene {
  const nodes: SceneNode[] = [
    { id: 'telegram', label: 'Telegram', position: new THREE.Vector3(-5.1, 2.7, -1.6), color: cssColor('--channel-telegram', '#2FA8E0') },
    { id: 'whatsapp', label: 'WhatsApp', position: new THREE.Vector3(5.2, 2.4, -1.0), color: cssColor('--channel-whatsapp', '#3FD07A') },
    { id: 'shopee', label: 'Shopee', position: new THREE.Vector3(-4.9, -2.7, 0.9), color: cssColor('--channel-shopee', '#F1642E') },
    { id: 'instagram', label: 'Instagram', position: new THREE.Vector3(5.0, -2.5, 1.4), color: cssColor('--channel-instagram', '#C64BB4') },
  ]
  const accent = cssColor('--accent', '#F0A24B')

  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: false,
    alpha: true,
    powerPreference: 'high-performance',
  })
  // Capped at 2. A 3x phone display would otherwise render nine times the
  // pixels of a 1x one for an effect nobody can resolve.
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 2)
  renderer.setPixelRatio(pixelRatio)
  renderer.setSize(window.innerWidth, window.innerHeight, false)
  renderer.setClearColor(0x000000, 0)

  const scene = new THREE.Scene()
  const flowGroup = new THREE.Group()
  scene.add(flowGroup)
  const camera = new THREE.PerspectiveCamera(
    50,
    window.innerWidth / window.innerHeight,
    0.1,
    100,
  )
  camera.position.set(0, 0, CAMERA_Z_START)

  // --- the particles ------------------------------------------------------
  const count = options.particles
  const geometry = new THREE.BufferGeometry()
  const channels = new Float32Array(count)
  const phases = new Float32Array(count)
  const speeds = new Float32Array(count)
  const spreads = new Float32Array(count)
  const jitter = new Float32Array(count * 3)
  // Every particle's position comes from the shader, but three.js still wants
  // a position attribute to know how many there are.
  const seed = new Float32Array(count * 3)

  for (let i = 0; i < count; i += 1) {
    channels[i] = i % nodes.length
    phases[i] = Math.random()
    speeds[i] = 0.05 + Math.random() * 0.08
    // sqrt, not a square: squaring pushes almost every particle to spread ~0,
    // which puts them all back on one curve. This fills the volume instead.
    spreads[i] = 0.18 + Math.sqrt(Math.random()) * 0.82

    // A point in a unit ball, so the perturbation is isotropic. Sampling each
    // axis independently would bias the cloud towards its corners.
    let x = 0
    let y = 0
    let z = 0
    let lengthSquared = 0
    do {
      x = Math.random() * 2 - 1
      y = Math.random() * 2 - 1
      z = Math.random() * 2 - 1
      lengthSquared = x * x + y * y + z * z
    } while (lengthSquared > 1 || lengthSquared === 0)
    jitter[i * 3] = x
    jitter[i * 3 + 1] = y
    jitter[i * 3 + 2] = z * 0.6
  }

  geometry.setAttribute('position', new THREE.BufferAttribute(seed, 3))
  geometry.setAttribute('aChannel', new THREE.BufferAttribute(channels, 1))
  geometry.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1))
  geometry.setAttribute('aSpeed', new THREE.BufferAttribute(speeds, 1))
  geometry.setAttribute('aSpread', new THREE.BufferAttribute(spreads, 1))
  geometry.setAttribute('aJitter', new THREE.BufferAttribute(jitter, 3))
  // The shader ignores `position`, so three.js cannot compute a useful bounding
  // sphere and would frustum-cull the whole cloud.
  geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 12)

  const material = new THREE.ShaderMaterial({
    vertexShader: VERTEX_SHADER,
    fragmentShader: FRAGMENT_SHADER,
    transparent: true,
    depthWrite: false,
    depthTest: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      uTime: { value: 0 },
      uProgress: { value: 0 },
      uSize: { value: 2.6 },
      uPixelRatio: { value: pixelRatio },
      uNodes: { value: nodes.map((n) => n.position) },
      uColors: { value: nodes.map((n) => n.color) },
      uAccent: { value: accent },
    },
  })

  const points = new THREE.Points(geometry, material)
  points.frustumCulled = false
  flowGroup.add(points)

  // --- the core -----------------------------------------------------------
  const coreMaterial = new THREE.ShaderMaterial({
    vertexShader: CORE_VERTEX,
    fragmentShader: CORE_FRAGMENT,
    transparent: true,
    depthWrite: false,
    depthTest: false,
    blending: THREE.AdditiveBlending,
    uniforms: { uAccent: { value: accent }, uIntensity: { value: 0.25 } },
  })
  const core = new THREE.Mesh(new THREE.PlaneGeometry(4.2, 4.2), coreMaterial)
  flowGroup.add(core)

  // A faint faceted shell gives the convergence point an actual volume. It
  // uses no lights or postprocessing and costs only a few dozen triangles.
  const shellMaterial = new THREE.MeshBasicMaterial({
    color: accent,
    transparent: true,
    opacity: 0.1,
    wireframe: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  })
  const shell = new THREE.Mesh(new THREE.IcosahedronGeometry(0.48, 2), shellMaterial)
  flowGroup.add(shell)

  // --- state --------------------------------------------------------------
  let progress = 0
  let running = false
  let frame = 0
  let onScreen = true
  let visible = typeof document === 'undefined' || document.visibilityState === 'visible'
  const clock = new THREE.Clock()
  const pointer = new THREE.Vector2()
  const pointerTarget = new THREE.Vector2()

  function render() {
    const elapsed = clock.getElapsedTime()
    material.uniforms.uTime.value = elapsed
    pointer.lerp(pointerTarget, 0.035)
    flowGroup.rotation.y = pointer.x * 0.11 + progress * 0.16
    flowGroup.rotation.x = -pointer.y * 0.075
    flowGroup.rotation.z = Math.sin(progress * Math.PI) * -0.055
    flowGroup.position.x = pointer.x * 0.18
    flowGroup.position.y = pointer.y * 0.12
    shell.rotation.x = elapsed * 0.12 + progress
    shell.rotation.y = elapsed * -0.16 + progress * 1.4
    renderer.render(scene, camera)
  }

  function loop() {
    if (!running) return
    render()
    frame = requestAnimationFrame(loop)
  }

  function governor() {
    // The loop runs only when the canvas is both on screen and in a visible
    // tab. A landing page quietly burning a laptop battery in a background tab
    // is the same failure as one that stutters.
    const shouldRun = onScreen && visible && !options.reducedMotion
    if (shouldRun && !running) {
      running = true
      clock.getDelta()
      frame = requestAnimationFrame(loop)
    } else if (!shouldRun && running) {
      running = false
      cancelAnimationFrame(frame)
    }
  }

  const observer =
    typeof IntersectionObserver !== 'undefined'
      ? new IntersectionObserver(
          ([entry]) => {
            onScreen = entry?.isIntersecting ?? true
            governor()
          },
          { threshold: 0 },
        )
      : null
  observer?.observe(canvas)

  function onVisibility() {
    visible = document.visibilityState === 'visible'
    governor()
  }
  document.addEventListener('visibilitychange', onVisibility)

  function onPointerMove(event: PointerEvent) {
    pointerTarget.set(
      (event.clientX / window.innerWidth) * 2 - 1,
      -((event.clientY / window.innerHeight) * 2 - 1),
    )
  }
  window.addEventListener('pointermove', onPointerMove, { passive: true })

  function onResize() {
    camera.aspect = window.innerWidth / window.innerHeight
    camera.updateProjectionMatrix()
    renderer.setSize(window.innerWidth, window.innerHeight, false)
    if (!running) render()
  }
  window.addEventListener('resize', onResize)

  const api: ConvergenceScene = {
    setProgress(value: number) {
      progress = Math.min(1, Math.max(0, value))
      material.uniforms.uProgress.value = progress
      // Arrival density rises as the flow tightens, so the core brightens
      // because more particles reach it -- not because a timeline said so.
      coreMaterial.uniforms.uIntensity.value = 0.18 + Math.pow(progress, 1.6) * 1.05
      core.scale.setScalar(1.0 - progress * 0.35)
      shell.scale.setScalar(0.86 + progress * 0.7)
      shellMaterial.opacity = 0.06 + progress * 0.18
      if (!running) render()
    },

    setCameraZ(z: number) {
      camera.position.z = z
      if (!running) render()
    },

    renderOnce: render,

    start() {
      if (options.reducedMotion) {
        // One static composed frame, no RAF loop, no scrub.
        api.setProgress(0.5)
        api.setCameraZ((CAMERA_Z_START + CAMERA_Z_END) / 2)
        render()
        return
      }
      governor()
    },

    stop() {
      running = false
      cancelAnimationFrame(frame)
    },

    dispose() {
      api.stop()
      observer?.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('resize', onResize)
      window.removeEventListener('pointermove', onPointerMove)
      geometry.dispose()
      material.dispose()
      core.geometry.dispose()
      coreMaterial.dispose()
      shell.geometry.dispose()
      shellMaterial.dispose()
      renderer.dispose()
    },

    nodeScreenPositions() {
      // Projected each frame so the labels stay glued to their node. They are
      // real DOM text, not canvas text: selectable, screen-readable and crisp,
      // none of which canvas text is.
      const half = new THREE.Vector2(window.innerWidth / 2, window.innerHeight / 2)
      return nodes.map((node) => {
        const projected = node.position.clone().applyMatrix4(flowGroup.matrixWorld).project(camera)
        const x = projected.x * half.x + half.x
        const y = -projected.y * half.y + half.y
        return {
          id: node.id,
          label: node.label,
          x,
          y,
          // Hidden at the top of the page. The spec's beat table names the
          // channels at progress 0.20, and showing them over the headline in
          // the hero is exactly the collision that beat exists to avoid.
          //
          // Also hidden once the node projects outside the viewport: a label
          // pinned to an edge no longer points at anything, it just sits
          // there being a word.
          visible:
            projected.z < 1 &&
            progress > 0.12 &&
            x > LABEL_MARGIN &&
            x < window.innerWidth - LABEL_MARGIN &&
            y > LABEL_MARGIN &&
            y < window.innerHeight - LABEL_MARGIN,
        }
      })
    },
  }

  return api
}
