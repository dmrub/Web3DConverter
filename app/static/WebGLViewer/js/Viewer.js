/**
 * Created by Dmitri Rubinstein on 2016-08-19.
 * Based on Three.js Demos
 */


if ( ! Detector.webgl ) {
    Detector.addGetWebGLMessage();
}

var orbitControls = null;
var container, stats;
var camera, scene, renderer, objects;
var clock = new THREE.Clock();

// init scene
init();

var onProgress = function ( xhr ) {
    if ( xhr.lengthComputable ) {
        var percentComplete = xhr.loaded / xhr.total * 100;
        console.log( Math.round(percentComplete, 2) + '% downloaded' );
    }
};

var onError = function ( xhr ) {
};


// Load jeep model using the AssimpJSONLoader
//			var loader1 = new THREE.AssimpJSONLoader();
//			loader1.load( 'models/assimp/lunar.assimp.json', function ( object ) {
//
//				object.scale.multiplyScalar( 0.2 );
//				scene.add( object );
//
//			}, onProgress, onError );


var loader = new THREE.ColladaLoader();
loader.options.convertUpAxis = true;

var queryParams = URI.parseQuery(window.location.search);
if (queryParams.uri) {
    console.log("Loading "+queryParams.uri);
    loader.load( queryParams.uri, function ( collada ) {

        dae = collada.scene;

        dae.traverse( function ( child ) {

            if ( child instanceof THREE.SkinnedMesh ) {

                var animation = new THREE.Animation( child, child.geometry.animation );
                animation.play();

            }

        });

        dae.scale.x = dae.scale.y = dae.scale.z = 1;
        dae.updateMatrix();

        // Add loaded scene

        scene.add( dae );

    }, onProgress, onError );
}


animate();

function init() {

    container = document.createElement( 'div' );
    document.body.appendChild( container );

    camera = new THREE.PerspectiveCamera( 50, window.innerWidth / window.innerHeight, 1, 2000 );
    camera.position.set( 2, 4, 5 );

    scene = new THREE.Scene();
    //scene.fog = new THREE.FogExp2( 0x000000, 0.035 );

    // Grid

    var size = 14, step = 1;

    var geometry = new THREE.Geometry();
    var material = new THREE.LineBasicMaterial( { color: 0x303030 } );

    for ( var i = - size; i <= size; i += step ) {

        geometry.vertices.push( new THREE.Vector3( - size, - 0.04, i ) );
        geometry.vertices.push( new THREE.Vector3(   size, - 0.04, i ) );

        geometry.vertices.push( new THREE.Vector3( i, - 0.04, - size ) );
        geometry.vertices.push( new THREE.Vector3( i, - 0.04,   size ) );

    }

    var line = new THREE.LineSegments( geometry, material );
    scene.add( line );


    // Lights
    scene.add( new THREE.AmbientLight( 0xcccccc ) );

    var directionalLight = new THREE.DirectionalLight( 0xeeeeee );
    directionalLight.position.x = Math.random() - 0.5;
    directionalLight.position.y = Math.random();
    directionalLight.position.z = Math.random() - 0.5;
    directionalLight.position.normalize();
    scene.add( directionalLight );

    // Renderer
    renderer = new THREE.WebGLRenderer();
    renderer.setPixelRatio( window.devicePixelRatio );
    renderer.setSize( window.innerWidth, window.innerHeight );
    container.appendChild( renderer.domElement );

    // Stats
    stats = new Stats();
    container.appendChild( stats.dom );

    // Events
    window.addEventListener( 'resize', onWindowResize, false );

    orbitControls = new THREE.OrbitControls(camera, renderer.domElement);
}

//

function onWindowResize( event ) {
    renderer.setSize( window.innerWidth, window.innerHeight );
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
}

//

function animate() {
    requestAnimationFrame( animate );
    orbitControls.update();
    render();
    stats.update();
}


function render() {
    THREE.AnimationHandler.update( clock.getDelta() );
    renderer.render( scene, camera );
}
