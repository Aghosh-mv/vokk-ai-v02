window.VOKKWorld3D = function VOKKWorld3D(spec) {
  const canvas = document.getElementById("c");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.08;
  renderer.shadowMap.enabled = !!spec.shadow;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(spec.background);
  scene.fog = new THREE.FogExp2(spec.fog[0], spec.fog[1]);

  const camera = new THREE.PerspectiveCamera(55, 2, 0.1, 100);
  camera.position.set(spec.camera[0], spec.camera[1], spec.camera[2]);
  camera.lookAt(spec.lookat[0], spec.lookat[1], spec.lookat[2]);

  scene.add(new THREE.AmbientLight(spec.ambient[0], spec.ambient[1]));
  scene.add(new THREE.HemisphereLight(spec.hemi[0], spec.hemi[1], spec.hemi[2]));

  const dir = new THREE.DirectionalLight(spec.directional[3], spec.directional[4]);
  dir.position.set(spec.directional[0], spec.directional[1], spec.directional[2]);
  dir.castShadow = !!spec.shadow;
  dir.shadow.mapSize.set(2048, 2048);
  dir.shadow.bias = -0.00025;
  dir.shadow.camera.near = 0.5;
  dir.shadow.camera.far = 40;
  dir.shadow.camera.left = -12;
  dir.shadow.camera.right = 12;
  dir.shadow.camera.top = 12;
  dir.shadow.camera.bottom = -12;
  scene.add(dir);

  const skyGeo = new THREE.SphereGeometry(60, 48, 32);
  const skyMat = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    depthWrite: false,
    uniforms: {
      topColor: { value: new THREE.Color(spec.horizon[0]) },
      bottomColor: { value: new THREE.Color(spec.horizon[1]) },
      offset: { value: 12 },
      exponent: { value: 0.9 },
    },
    vertexShader: "varying vec3 vWorldPosition;void main(){ vec4 worldPosition = modelMatrix * vec4(position, 1.0); vWorldPosition = worldPosition.xyz; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: "uniform vec3 topColor; uniform vec3 bottomColor; uniform float offset; uniform float exponent; varying vec3 vWorldPosition;void main(){ float h = normalize(vWorldPosition + offset).y; gl_FragColor = vec4(mix(bottomColor, topColor, max(pow(max(h, 0.0), exponent), 0.0)), 1.0); }",
  });
  scene.add(new THREE.Mesh(skyGeo, skyMat));

  const sun = new THREE.Mesh(
    new THREE.SphereGeometry(spec.sun[3], 32, 24),
    new THREE.MeshBasicMaterial({ color: spec.sun[4] })
  );
  sun.position.set(spec.sun[0], spec.sun[1], spec.sun[2]);
  scene.add(sun);

  const sunGlow = new THREE.Sprite(
    new THREE.SpriteMaterial({
      color: spec.sun[4],
      transparent: true,
      opacity: spec.sun[5] * 0.28,
    })
  );
  sunGlow.scale.set(spec.sun[3] * 8.0, spec.sun[3] * 8.0, 1);
  sunGlow.position.copy(sun.position);
  scene.add(sunGlow);

  function matFor(o) {
    return new THREE.MeshPhysicalMaterial({
      color: o.color || "#cccccc",
      roughness: o.roughness == null ? 0.35 : o.roughness,
      metalness: o.metalness == null ? 0.18 : o.metalness,
      emissive: o.emissive || "#000000",
      emissiveIntensity: o.emissiveIntensity == null ? 0 : o.emissiveIntensity,
      clearcoat: 0.18,
      clearcoatRoughness: 0.22,
    });
  }

  for (const o of spec.objects || []) {
    let mesh;
    if (o.type === "box") mesh = new THREE.Mesh(new THREE.BoxGeometry(o.size, o.size, o.size), matFor(o));
    if (o.type === "sphere") mesh = new THREE.Mesh(new THREE.SphereGeometry(o.size, 64, 40), matFor(o));
    if (o.type === "torus") mesh = new THREE.Mesh(new THREE.TorusGeometry(o.size, o.tube, 48, 140), matFor(o));
    if (o.type === "cylinder") mesh = new THREE.Mesh(new THREE.CylinderGeometry(o.radius, o.radius, o.height, 48, 1), matFor(o));
    if (o.type === "capsule") mesh = new THREE.Mesh(new THREE.CapsuleGeometry(o.radius, o.height, 12, 24), matFor(o));
    if (o.type === "plane") mesh = new THREE.Mesh(new THREE.PlaneGeometry(o.w, o.h, 1, 1), matFor(o));
    if (o.type === "floor") {
      mesh = new THREE.Mesh(new THREE.CircleGeometry(o.size, 96), matFor(o));
      mesh.rotation.x = -Math.PI / 2;
      mesh.position.y = o.y;
      mesh.receiveShadow = !!spec.shadow;
      scene.add(mesh);
      continue;
    }
    if (!mesh) continue;
    mesh.position.set(o.x || 0, o.y || 0, o.z || 0);
    mesh.rotation.set(o.rx || 0, o.ry || 0, o.rz || 0);
    mesh.castShadow = !!spec.shadow;
    mesh.receiveShadow = !!spec.shadow;
    scene.add(mesh);
  }

  const controls = spec.orbit ? new THREE.OrbitControls(camera, renderer.domElement) : null;
  if (controls) {
    controls.enableDamping = true;
    controls.target.set(spec.lookat[0], spec.lookat[1], spec.lookat[2]);
  }

  function resize() {
    const w = window.innerWidth;
    const h = window.innerHeight;
    if (canvas.width !== w || canvas.height !== h) {
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }
  }

  function tick(t) {
    resize();
    sunGlow.material.opacity = 0.18 + Math.sin(t * 0.00035) * 0.04 + spec.sun[5] * 0.16;
    if (controls) controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(tick);
  }

  requestAnimationFrame(tick);
};
