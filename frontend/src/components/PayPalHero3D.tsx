import { useEffect, useRef } from "react";
import * as THREE from "three";

export type Hero3DMode = "settled" | "clamped" | "shielded";

interface PayPalBackdrop3DProps {
  mode?: Hero3DMode;
}

const MODE_RING_COLORS: Record<
  Hero3DMode,
  { backHex: number; frontHex: number; overlapHex: number; ringHex: number }
> = {
  settled: {
    backHex: 0x003087,
    frontHex: 0x009cde,
    overlapHex: 0x012169,
    ringHex: 0x10b981,
  },
  clamped: {
    backHex: 0x003087,
    frontHex: 0x38bdf8,
    overlapHex: 0x0284c7,
    ringHex: 0xf59e0b,
  },
  shielded: {
    backHex: 0x002c77,
    frontHex: 0x60a5fa,
    overlapHex: 0x1d4ed8,
    ringHex: 0x38bdf8,
  },
};

/**
 * Authentic modern PayPal solid italic "P" ribbon silhouette
 * (matching the official Pentagram PayPal monogram curves and 12° forward shear).
 */
function createPayPalMonogramShape(): THREE.Shape {
  const shear = 0.21;
  const p = (x: number, y: number): [number, number] => [x + y * shear, y];

  const s = new THREE.Shape();

  const [x0, y0] = p(-0.78, -1.38);
  s.moveTo(x0, y0);

  const [x1, y1] = p(-0.78, 1.24);
  s.lineTo(x1, y1);

  const [tlCx, tlCy] = p(-0.78, 1.42);
  const [x2, y2] = p(-0.58, 1.42);
  s.quadraticCurveTo(tlCx, tlCy, x2, y2);

  const [x3, y3] = p(0.28, 1.42);
  s.lineTo(x3, y3);

  const [b1x, b1y] = p(1.08, 1.42);
  const [b2x, b2y] = p(1.22, 0.92);
  const [x4, y4] = p(1.16, 0.48);
  s.bezierCurveTo(b1x, b1y, b2x, b2y, x4, y4);

  const [b3x, b3y] = p(1.08, -0.04);
  const [b4x, b4y] = p(0.68, -0.32);
  const [x5, y5] = p(0.08, -0.32);
  s.bezierCurveTo(b3x, b3y, b4x, b4y, x5, y5);

  const [x6, y6] = p(-0.14, -0.32);
  s.lineTo(x6, y6);

  const [inCx, inCy] = p(-0.22, -0.32);
  const [x7, y7] = p(-0.22, -0.42);
  s.quadraticCurveTo(inCx, inCy, x7, y7);

  const [x8, y8] = p(-0.22, -1.38);
  s.lineTo(x8, y8);

  const [brCx, brCy] = p(-0.22, -1.48);
  const [x9, y9] = p(-0.34, -1.48);
  s.quadraticCurveTo(brCx, brCy, x9, y9);

  const [x10, y10] = p(-0.66, -1.48);
  s.lineTo(x10, y10);

  const [blCx, blCy] = p(-0.78, -1.48);
  s.quadraticCurveTo(blCx, blCy, x0, y0);

  return s;
}

export default function PayPalHero3D({ mode = "settled" }: PayPalBackdrop3DProps) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const modeRef = useRef<Hero3DMode>(mode);
  const pulseRef = useRef<number>(0);

  useEffect(() => {
    modeRef.current = mode;
    pulseRef.current = 1.0;
  }, [mode]);

  useEffect(() => {
    const container = mountRef.current;
    if (!container) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        powerPreference: "high-performance",
      });
    } catch {
      return;
    }

    const width = window.innerWidth || 1280;
    const height = window.innerHeight || 800;
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.18;

    container.innerHTML = "";
    container.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, width / height, 0.1, 120);
    camera.position.set(0, 0, 9.2);

    // Studio lighting rig
    const ambientLight = new THREE.AmbientLight(0xdbeafe, 1.55);
    scene.add(ambientLight);

    const keyLight = new THREE.DirectionalLight(0xffffff, 2.8);
    keyLight.position.set(5.5, 7.0, 6.5);
    scene.add(keyLight);

    const rimLightLeft = new THREE.PointLight(0x009cde, 6.0, 22);
    rimLightLeft.position.set(-5.0, 2.8, 4.5);
    scene.add(rimLightLeft);

    const statusLight = new THREE.PointLight(0x10b981, 4.8, 18);
    statusLight.position.set(4.2, -2.8, 4.2);
    scene.add(statusLight);

    const rootGroup = new THREE.Group();
    // Start positioned on the right side of the viewport to anchor the Hero bay
    rootGroup.position.set(2.15, 0.15, 0);
    scene.add(rootGroup);

    // 1. Extruded 3D PayPal Double-"P" Monogram
    const logoGroup = new THREE.Group();
    rootGroup.add(logoGroup);

    const pShape = createPayPalMonogramShape();
    const extrudeSettings: THREE.ExtrudeGeometryOptions = {
      depth: 0.3,
      bevelEnabled: true,
      bevelSegments: 8,
      steps: 1,
      bevelSize: 0.055,
      bevelThickness: 0.055,
      curveSegments: 42,
    };
    const pGeometry = new THREE.ExtrudeGeometry(pShape, extrudeSettings);
    pGeometry.center();

    // Back "P" — PayPal Deep Navy (#003087)
    const backPMaterial = new THREE.MeshPhysicalMaterial({
      color: 0x003087,
      metalness: 0.32,
      roughness: 0.18,
      clearcoat: 1.0,
      clearcoatRoughness: 0.08,
      emissive: 0x001c64,
      emissiveIntensity: 0.38,
      transparent: true,
      opacity: 0.9,
    });
    const backPMesh = new THREE.Mesh(pGeometry, backPMaterial);
    backPMesh.position.set(-0.26, 0.24, -0.2);
    logoGroup.add(backPMesh);

    // Mid Intersection "P" slice — Rich PayPal Overlap Navy (#012169)
    const midPMaterial = new THREE.MeshPhysicalMaterial({
      color: 0x012169,
      metalness: 0.38,
      roughness: 0.14,
      clearcoat: 1.0,
      emissive: 0x003087,
      emissiveIntensity: 0.32,
      transparent: true,
      opacity: 0.92,
    });
    const midPMesh = new THREE.Mesh(pGeometry, midPMaterial);
    midPMesh.scale.set(0.92, 0.92, 0.65);
    midPMesh.position.set(0.0, 0.0, 0.01);
    logoGroup.add(midPMesh);

    // Front "P" — PayPal Cyan (#009cde)
    const frontPMaterial = new THREE.MeshPhysicalMaterial({
      color: 0x009cde,
      metalness: 0.18,
      roughness: 0.14,
      clearcoat: 1.0,
      clearcoatRoughness: 0.06,
      emissive: 0x0070ba,
      emissiveIntensity: 0.34,
      transparent: true,
      opacity: 0.88,
    });
    const frontPMesh = new THREE.Mesh(pGeometry, frontPMaterial);
    frontPMesh.position.set(0.26, -0.24, 0.22);
    logoGroup.add(frontPMesh);

    // Architectural wireframe contour on the front "P"
    const edgeGeo = new THREE.EdgesGeometry(pGeometry, 28);
    const edgeMat = new THREE.LineBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.28,
    });
    const edgeLines = new THREE.LineSegments(edgeGeo, edgeMat);
    frontPMesh.add(edgeLines);

    // 2. Orbital Guardrail Rings
    const ringsGroup = new THREE.Group();
    rootGroup.add(ringsGroup);

    const innerRingGeo = new THREE.TorusGeometry(2.25, 0.02, 20, 140);
    const innerRingMat = new THREE.MeshStandardMaterial({
      color: 0x10b981,
      emissive: 0x10b981,
      emissiveIntensity: 0.55,
      metalness: 0.5,
      roughness: 0.2,
      transparent: true,
      opacity: 0.78,
    });
    const innerRing = new THREE.Mesh(innerRingGeo, innerRingMat);
    innerRing.rotation.x = Math.PI * 0.38;
    innerRing.rotation.y = Math.PI * 0.14;
    ringsGroup.add(innerRing);

    const sentinelGeo = new THREE.SphereGeometry(0.068, 16, 16);
    const sentinelMat = new THREE.MeshBasicMaterial({ color: 0x34d399 });
    for (let i = 0; i < 3; i++) {
      const angle = (i * Math.PI * 2) / 3;
      const node = new THREE.Mesh(sentinelGeo, sentinelMat);
      node.position.set(Math.cos(angle) * 2.25, Math.sin(angle) * 2.25, 0);
      innerRing.add(node);
    }

    const midRingGeo = new THREE.TorusGeometry(2.75, 0.014, 16, 150);
    const midRingMat = new THREE.MeshStandardMaterial({
      color: 0x009cde,
      emissive: 0x0070ba,
      emissiveIntensity: 0.4,
      metalness: 0.6,
      roughness: 0.25,
      transparent: true,
      opacity: 0.62,
    });
    const midRing = new THREE.Mesh(midRingGeo, midRingMat);
    midRing.rotation.x = -Math.PI * 0.32;
    midRing.rotation.y = -Math.PI * 0.22;
    ringsGroup.add(midRing);

    const outerRingGeo = new THREE.TorusGeometry(3.25, 0.009, 12, 160);
    const outerRingMat = new THREE.MeshBasicMaterial({
      color: 0x64748b,
      transparent: true,
      opacity: 0.28,
    });
    const outerRing = new THREE.Mesh(outerRingGeo, outerRingMat);
    outerRing.rotation.x = Math.PI * 0.46;
    ringsGroup.add(outerRing);

    // 3. Full-Viewport Ambient 3D Ledger Particle Field
    const particleCount = 220;
    const positions = new Float32Array(particleCount * 3);
    for (let i = 0; i < particleCount; i++) {
      const r = 2.4 + Math.random() * 5.2;
      const theta = Math.random() * Math.PI * 2;
      const phi = (Math.random() - 0.5) * Math.PI * 0.9;
      positions[i * 3] = r * Math.cos(theta) * Math.cos(phi);
      positions[i * 3 + 1] = r * Math.sin(phi);
      positions[i * 3 + 2] = r * Math.sin(theta) * Math.cos(phi);
    }
    const particleGeo = new THREE.BufferGeometry();
    particleGeo.setAttribute(
      "position",
      new THREE.BufferAttribute(positions, 3),
    );
    const particleMat = new THREE.PointsMaterial({
      color: 0x0284c7,
      size: 0.048,
      transparent: true,
      opacity: 0.45,
    });
    const particles = new THREE.Points(particleGeo, particleMat);
    scene.add(particles);

    // Scroll & pointer state
    let pointerX = 0;
    let pointerY = 0;
    let scrollProgress = 0;

    const updateScroll = () => {
      const docHeight = Math.max(
        document.documentElement.scrollHeight - window.innerHeight,
        1,
      );
      scrollProgress = Math.max(0, Math.min(1, window.scrollY / docHeight));
    };
    updateScroll();

    const handlePointerMove = (e: PointerEvent) => {
      const w = Math.max(window.innerWidth, 1);
      const h = Math.max(window.innerHeight, 1);
      pointerX = (e.clientX / w) * 2 - 1;
      pointerY = (e.clientY / h) * 2 - 1;
    };

    const handleResize = () => {
      const w = window.innerWidth || 1280;
      const h = window.innerHeight || 800;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
      updateScroll();
    };

    window.addEventListener("scroll", updateScroll, { passive: true });
    window.addEventListener("pointermove", handlePointerMove, { passive: true });
    window.addEventListener("resize", handleResize);

    const clock = new THREE.Clock();
    let frameId = 0;
    let smoothScroll = scrollProgress;

    const animate = () => {
      frameId = window.requestAnimationFrame(animate);
      const elapsed = clock.getElapsedTime();
      const colors = MODE_RING_COLORS[modeRef.current];

      // Smoothly damp scroll progress (0 at top hero -> 1 at footer)
      smoothScroll += (scrollProgress - smoothScroll) * 0.06;

      pulseRef.current = Math.max(0, pulseRef.current * 0.92);
      const pulseBoost = 1 + pulseRef.current * 0.12;

      innerRingMat.color.lerp(new THREE.Color(colors.ringHex), 0.08);
      innerRingMat.emissive.lerp(new THREE.Color(colors.ringHex), 0.08);
      sentinelMat.color.lerp(new THREE.Color(colors.ringHex), 0.08);
      statusLight.color.lerp(new THREE.Color(colors.ringHex), 0.08);
      frontPMaterial.color.lerp(new THREE.Color(colors.frontHex), 0.08);
      midPMaterial.color.lerp(new THREE.Color(colors.overlapHex), 0.08);

      // Scroll-choreographed 3D path across the backdrop:
      // - At top (scroll = 0): sits at x = +2.25 (right side of Hero)
      // - Mid-page (scroll ~ 0.45): sweeps across to x = -2.1 (left side behind Pipeline/Bento)
      // - Lower-page (scroll ~ 0.85): glides toward center-right (x = +1.4)
      const isCompactViewport = window.innerWidth < 1080;
      const targetX = isCompactViewport
        ? Math.sin(smoothScroll * Math.PI * 2) * 0.65
        : Math.cos(smoothScroll * Math.PI * 1.65) * 2.25;
      const targetY =
        0.18 -
        smoothScroll * 0.35 +
        Math.sin(elapsed * 1.4) * 0.08;
      const targetZ = -smoothScroll * 1.15;

      rootGroup.position.x += (targetX - rootGroup.position.x) * 0.06;
      rootGroup.position.y += (targetY - rootGroup.position.y) * 0.06;
      rootGroup.position.z += (targetZ - rootGroup.position.z) * 0.06;

      // Scroll-driven 3D rotation + cursor parallax
      const targetRotY =
        -0.28 +
        smoothScroll * Math.PI * 1.35 +
        pointerX * 0.32 +
        Math.sin(elapsed * 0.7) * 0.12;
      const targetRotX =
        0.06 +
        Math.sin(smoothScroll * Math.PI) * 0.28 +
        pointerY * 0.2;
      const targetRotZ = Math.sin(smoothScroll * Math.PI * 2) * 0.14;

      rootGroup.rotation.y += (targetRotY - rootGroup.rotation.y) * 0.06;
      rootGroup.rotation.x += (targetRotX - rootGroup.rotation.x) * 0.06;
      rootGroup.rotation.z += (targetRotZ - rootGroup.rotation.z) * 0.06;

      logoGroup.scale.setScalar(pulseBoost);

      // Subtle breathing depth separation between the two PayPal "P" layers
      frontPMesh.position.z = 0.22 + Math.sin(elapsed * 2.0) * 0.035;
      backPMesh.position.z = -0.2 - Math.sin(elapsed * 2.0) * 0.025;

      // Orbital guardrail ring motion accelerated by scroll velocity
      const spinSpeed = modeRef.current === "clamped" ? 1.4 : 0.85;
      innerRing.rotation.z += 0.007 * spinSpeed;
      midRing.rotation.z -= 0.005 * spinSpeed;
      outerRing.rotation.z += 0.003 * spinSpeed;

      // Expand rings slightly as user scrolls deeper into the architecture
      const ringScale = 1 + smoothScroll * 0.18;
      ringsGroup.scale.setScalar(ringScale);

      // Ambient ledger particle field drifts with scroll and time
      particles.rotation.y = elapsed * 0.04 + smoothScroll * 0.9;
      particles.position.y = smoothScroll * 1.4;

      renderer.render(scene, camera);
    };

    animate();

    return () => {
      window.cancelAnimationFrame(frameId);
      window.removeEventListener("scroll", updateScroll);
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("resize", handleResize);
      pGeometry.dispose();
      edgeGeo.dispose();
      edgeMat.dispose();
      backPMaterial.dispose();
      midPMaterial.dispose();
      frontPMaterial.dispose();
      innerRingGeo.dispose();
      innerRingMat.dispose();
      midRingGeo.dispose();
      midRingMat.dispose();
      outerRingGeo.dispose();
      outerRingMat.dispose();
      particleGeo.dispose();
      particleMat.dispose();
      renderer.dispose();
    };
  }, []);

  return (
    <div
      ref={mountRef}
      className="tk-webgl-backdrop"
      aria-hidden="true"
    />
  );
}
