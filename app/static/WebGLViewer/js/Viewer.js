/**
 * Created by Dmitri Rubinstein on 2016-08-19.
 * Based on Three.js Demos
 */


if (!Detector.webgl) {
    Detector.addGetWebGLMessage();
}

var Viewer = Viewer || {};

var requestAnimationFrame = window.requestAnimationFrame || window.mozRequestAnimationFrame ||
    window.webkitRequestAnimationFrame || window.msRequestAnimationFrame;


var cancelAnimationFrame = window.cancelAnimationFrame || window.mozCancelAnimationFrame;

// Load jeep model using the AssimpJSONLoader
//			var loader1 = new THREE.AssimpJSONLoader();
//			loader1.load( 'models/assimp/lunar.assimp.json', function ( object ) {
//
//				object.scale.multiplyScalar( 0.2 );
//				scene.add( object );
//
//			}, onProgress, onError );

function loadCollada(scene, uri, options) {

    var options = options || {};

    var onProgress = options.onProgress || function (xhr) {
            if (xhr.lengthComputable) {
                var percentComplete = xhr.loaded / xhr.total * 100;
                console.log(Math.round(percentComplete, 2) + '% downloaded');
            }
        };

    var onError = options.onError || function (xhr) {
        };

    var loader = new THREE.ColladaLoader();
    loader.options.convertUpAxis = true;

    console.log("Loading " + uri);
    loader.load(uri, function (collada) {

        if (options.onLoad)
            options.onLoad(collada);

        dae = collada.scene;

        dae.traverse(function (child) {

            if (child instanceof THREE.SkinnedMesh) {

                var animation = new THREE.Animation(child, child.geometry.animation);
                animation.play();

            }

        });

        dae.scale.x = dae.scale.y = dae.scale.z = 1;
        dae.updateMatrix();

        var box = new THREE.Box3().setFromObject(dae);

        // Add loaded scene

        scene.add(dae);

    }, options.onProgress, options.onError);
}

function createGrid(scene, size, step) {
    var geometry = new THREE.Geometry();
    var material = new THREE.LineBasicMaterial({color: 0x303030});

    for (var i = -size; i <= size; i += step) {

        geometry.vertices.push(new THREE.Vector3(-size, -0.04, i));
        geometry.vertices.push(new THREE.Vector3(size, -0.04, i));

        geometry.vertices.push(new THREE.Vector3(i, -0.04, -size));
        geometry.vertices.push(new THREE.Vector3(i, -0.04, size));

    }

    var line = new THREE.LineSegments(geometry, material);
    scene.add(line);
}

Viewer.init = function () {

    var clock = new THREE.Clock();

    var container = document.createElement('div');
    document.body.appendChild(container);

    var camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 1, 2000);
    camera.position.set(2, 4, 5);

    var scene = new THREE.Scene();
    //scene.fog = new THREE.FogExp2( 0x000000, 0.035 );

    // Grid

    var size = 14, step = 1;

    createGrid(scene, size, step);

    // Lights
    scene.add(new THREE.AmbientLight(0xcccccc));

    var directionalLight = new THREE.DirectionalLight(0xeeeeee);
    directionalLight.position.x = Math.random() - 0.5;
    directionalLight.position.y = Math.random();
    directionalLight.position.z = Math.random() - 0.5;
    directionalLight.position.normalize();
    scene.add(directionalLight);

    // Renderer
    var renderer = new THREE.WebGLRenderer();
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(window.innerWidth, window.innerHeight);
    container.appendChild(renderer.domElement);

    // Stats
    var stats = new Stats();
    container.appendChild(stats.dom);

    // Events
    window.addEventListener('resize', Viewer.onWindowResize, false);

    var orbitControls = new THREE.OrbitControls(camera, renderer.domElement);

    Viewer.orbitControls = orbitControls;
    Viewer.container = container;
    Viewer.stats = stats;
    Viewer.camera = camera;
    Viewer.scene = scene;
    Viewer.renderer = renderer;
    Viewer.clock = clock;
}

Viewer.loadCollada = function(uri, options) {
    return loadCollada(Viewer.scene, uri, options);
}

//

Viewer.onWindowResize = function (event) {
    Viewer.renderer.setSize(window.innerWidth, window.innerHeight);
    Viewer.camera.aspect = window.innerWidth / window.innerHeight;
    Viewer.camera.updateProjectionMatrix();
}

//

Viewer.animate = function() {
    requestAnimationFrame(Viewer.animate);
    Viewer.orbitControls.update();
    Viewer.render();
    Viewer.stats.update();
}


Viewer.render = function() {
    THREE.AnimationHandler.update(Viewer.clock.getDelta());
    Viewer.renderer.render(Viewer.scene, Viewer.camera);
}
