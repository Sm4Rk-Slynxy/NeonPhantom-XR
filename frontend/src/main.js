import { mount } from 'svelte';
import App from './routes/+page.svelte';
import './app.css';

mount(App, { target: document.getElementById('app') });
