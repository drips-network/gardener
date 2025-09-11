import { PRIVATE_KEY } from '$env/static/private';

if (browser) {
    console.log('Running in browser');
} else {
    console.log('Running on server');
}