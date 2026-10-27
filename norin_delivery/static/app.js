'use strict';

const paths = {
  box: '<path d="m12 3 9 5v9l-9 5-9-5V8Z"/><path d="m3 8 9 5 9-5M12 13v9M7.5 5.5l9 5"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  requests: '<path d="M8 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2h-3"/><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M7 11h10M7 16h6"/>',
  quote: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2Z"/><path d="M9 7h6M9 11h6M9 15h3"/>',
  users: '<circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M16 5a3 3 0 0 1 0 6M21 20v-2a6 6 0 0 0-3-5"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
  arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  logout: '<path d="M9 4H4v16h5M9 12h12m-4-4 4 4-4 4"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
  shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 12 3 3 5-6"/>',
  location: '<path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 0 1 14 0Z"/><circle cx="12" cy="10" r="2"/>',
  edit: '<path d="m15 5 4 4M4 20l4-1L20 7a2.8 2.8 0 0 0-4-4L4 15Z"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  power: '<path d="M12 2v10M6 5a9 9 0 1 0 12 0"/>',
  leaf: '<path d="M20 3C8 2 2 8 5 16c8 3 14-1 15-13ZM4 21 15 10"/>',
};
const icon = (name) => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.box}</svg>`;
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $ = (selector, root = document) => root.querySelector(selector);
const money = value => new Intl.NumberFormat('en-AU', {style:'currency', currency:'AUD'}).format(Number(value || 0));
const date = value => value ? new Date(value).toLocaleString('en-AU', {day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}) : '—';
const shortId = id => `#${String(id).split('-').pop().slice(-6).toUpperCase()}`;
const badge = status => `<span class="badge ${esc(status.toLowerCase())}">${esc(status)}</span>`;
const brand = () => `<div class="brand"><span class="brand-mark">${icon('box')}</span><div><div class="brand-name">Your Order</div><div class="brand-caption">WE DELIVER</div></div></div>`;
let state = {actor:null, requests:[], customers:[], quotes:[], accounts:[], deliveries:[], delivery_staff:[], schedules:[], allocations:[], delivery_events:[], payments:[], view:'overview', filter:'All', search:'', authMode:'login'};
let toastTimer;
let afterCustomer = false;

async function api(path, data) {
  const options = {headers:{}, credentials:'same-origin'};
  if (data !== undefined) {
    options.method = 'POST';
    options.headers = {'Content-Type':'application/json','X-CSRF-Token':state.csrf || ''};
    options.body = JSON.stringify(data);
  }
  let response;
  try { response = await fetch(path, options); }
  catch { throw new Error('The local app is not responding. Reopen Your Order and try again.'); }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Something went wrong. Please try again.');
  return result;
}

function notify(message) {
  const element = $('#toast');
  element.textContent = message;
  element.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove('visible'), 4200);
}

function button(label, action, {kind='primary', symbol='', id='', extra=''} = {}) {
  return `<button type="button" class="btn ${kind}" data-action="${action}" ${id ? `data-id="${esc(id)}"` : ''} ${extra}>${symbol ? icon(symbol) : ''}${label}</button>`;
}

function field(label, name, {type='text', value='', placeholder='', hint='', required=false, autocomplete='', extra=''} = {}) {
  return `<div class="field"><label for="field-${name}">${label}</label><input id="field-${name}" name="${name}" type="${type}" value="${esc(value)}" placeholder="${esc(placeholder)}" ${required ? 'required' : ''} ${autocomplete ? `autocomplete="${autocomplete}"` : ''} ${extra}>${hint ? `<div class="field-hint">${hint}</div>` : ''}</div>`;
}

function formError() { return '<div class="form-error" role="alert" tabindex="-1"></div>'; }
function office() { return ['Manager','Office staff'].includes(state.actor?.role); }
function customerName(id) { return state.customers.find(c => c.customer_id === id)?.display_name || 'Customer'; }
function initials(name) { return String(name).split(/[\s_.-]+/).map(s => s[0]).slice(0,2).join('').toUpperCase(); }
function route(request) {
  return `<div class="route"><div><span class="route-dot"></span>${esc(request.pickup_address || 'Pickup not added')}</div><div><span class="route-dot destination"></span>${esc(request.destination_address || 'Destination not added')}</div></div>`;
}
function empty(title, description, action='', label='New request', symbol='box') {
  return `<div class="empty"><div class="empty-icon">${icon(symbol)}</div><h3>${title}</h3><p>${description}</p>${action ? button(label,action,{symbol:'plus'}) : ''}</div>`;
}

function auth() {
  const mode = state.needs_setup ? 'setup' : state.authMode;
  const setup = mode === 'setup', register = mode === 'register';
  const title = setup ? 'Make yourself at home.' : register ? 'Your next delivery starts here.' : 'Welcome back.';
  const description = setup ? 'Create the first manager account to open your delivery workspace.' : register ? 'Create a customer account to request deliveries and review your quotes.' : 'Sign in to manage your requests, review quotes and keep things moving.';
  $('#app').innerHTML = `<div class="auth"><aside class="auth-story">${brand()}<div class="auth-copy"><div class="eyebrow">A clearer way to deliver</div><h1>Every parcel.<br>One <em>simple journey.</em></h1><p>From your first request to your accepted quote. Keep the details together, every step of the way.</p></div><div class="route-art" aria-hidden="true"><div class="art-card"><span class="art-symbol">${icon('box')}</span><div><strong>A request, ready to go</strong><small>The details that start the journey</small></div><span class="art-tick">${icon('check')}</span></div><div class="art-connector"></div><div class="art-card"><span class="art-symbol">${icon('quote')}</span><div><strong>A quote, made clear</strong><small>Review the terms. Make your decision.</small></div></div></div><div class="auth-story-footer"><span>Made for deliveries around Melbourne.</span><span>YOUR ORDER · WE DELIVER</span></div></aside><main id="main" class="auth-main"><div class="auth-topline">${icon('shield')} Your local delivery workspace</div><div class="auth-form-wrap"><div class="eyebrow">${setup ? 'Let’s get you started' : register ? 'Customer registration' : 'Your delivery workspace'}</div><h2>${title}</h2><p class="auth-description">${description}</p><form data-form="${mode}">${formError()}${register ? contactFields() : ''}${field('Username','username',{required:true,placeholder:setup ? 'Choose a manager username' : register ? 'e.g. norinung48' : 'Enter your username',hint:register ? 'Use 3-40 letters, numbers, dots, _ or -. Put your email in the Email field above.' : setup ? 'Use 3-40 letters, numbers, dots, _ or -.' : '',autocomplete:'username'})}${field('Password','password',{type:'password',required:true,placeholder:mode === 'login' ? 'Enter your password' : 'At least 8 characters',autocomplete:mode === 'login' ? 'current-password' : 'new-password',extra:mode === 'login' ? '' : 'minlength="8"'})}${mode !== 'login' ? field('Confirm password','confirm_password',{type:'password',required:true,placeholder:'Enter your password again',autocomplete:'new-password'}) : ''}<button class="btn primary full-width" type="submit">${setup ? 'Create workspace' : register ? 'Create account' : 'Sign in'}${icon('arrow')}</button></form>${!setup ? `<p class="auth-switch">${register ? 'Already have an account?' : 'New to Your Order?'} <button data-action="auth-switch" data-mode="${register ? 'login' : 'register'}">${register ? 'Sign in' : 'Create an account'}</button></p>` : ''}<div class="auth-help">${icon('shield')} Your data stays on this computer.</div></div></main></div>`;
}

function contactFields(customer = {}) {
  return `${field('Full name','name',{value:customer.display_name || '',required:true,placeholder:'Person or organisation',autocomplete:'name'})}<div class="form-row">${field('Phone <small>optional with email</small>','phone',{value:customer.phone || '',placeholder:'04xx xxx xxx',autocomplete:'tel',type:'tel'})}${field('Email <small>optional with phone</small>','email',{value:customer.email || '',placeholder:'you@example.com',autocomplete:'email',type:'email'})}</div>`;
}

function navigation(view, label, symbol, count=0) {
  return `<button class="nav-item ${state.view === view ? 'active' : ''}" data-action="navigate" data-view="${view}" ${state.view === view ? 'aria-current="page"' : ''}>${icon(symbol)}${label}${count ? `<span class="nav-count">${count}</span>` : ''}</button>`;
}

function render() {
  if (!state.actor) { auth(); return; }
  const titles = {overview:'Overview',requests:'Delivery requests',quotes:'Quotes',customers:'Customers',profile:'My details',accounts:'Team accounts',deliveries:'Deliveries',staff:'Staff & availability'};
  const actor = state.actor;
  const name = actor.role === 'Customer' ? customerName(actor.customer_id) : actor.username;
  const pending = state.quotes.filter(q => q.decision === 'Pending').length;
  $('#app').innerHTML = `<aside class="sidebar">${brand()}<div class="nav-label">WORKSPACE</div><nav aria-label="Main navigation">${navigation('overview','Overview','grid')}${!state.demo_delivery ? navigation('deliveries','Deliveries','box') : ''}${!state.demo_delivery && actor.role !== 'Customer' ? navigation('staff','Staff & availability','users') : ''}${navigation('requests','Delivery requests','requests')}${navigation('quotes','Quotes','quote',pending)}${office() ? navigation('customers','Customers','users') : actor.role === 'Customer' ? navigation('profile','My details','user') : ''}${actor.role === 'Manager' ? navigation('accounts','Team accounts','shield') : ''}</nav><div class="sidebar-bottom"><div class="workspace-note"><strong><span class="dot"></span>All changes saved locally</strong>Pick up where you left off, whenever you’re ready.</div><div class="sidebar-profile flex"><span class="avatar">${esc(initials(name))}</span><div class="grow"><div class="username">${esc(name)}</div><div class="role">${esc(actor.role)}</div></div><button class="icon-button" data-action="logout" title="Sign out" aria-label="Sign out">${icon('logout')}</button></div></div></aside><div class="shell"><header class="topbar"><div class="flex"><button class="icon-button mobile-menu" data-action="menu" aria-label="Toggle navigation">${icon('menu')}</button><div class="breadcrumb">Workspace <span>/</span> <strong>${titles[state.view] || 'Overview'}</strong></div></div><div class="topbar-meta"><span class="local-label"><span></span>Local workspace</span><span class="topbar-date">${new Date().toLocaleDateString('en-AU',{day:'numeric',month:'short',year:'numeric'})}</span><span class="avatar">${esc(initials(name))}</span></div></header><main id="main" class="main">${content()}<footer class="page-footer"><span>Your Order We Deliver · Melbourne</span><span>${state.demo_delivery ? 'Delivery handoff is in demo mode' : 'Connected delivery workspace'}</span></footer></main></div>`;
  if (actor.role === 'Manager') {
    $('.sidebar-bottom').insertAdjacentHTML('afterbegin', `<button class="nav-item" data-action="shutdown">${icon('power')}Close workspace</button>`);
  }
}

function heading(title, description, action='', label='', symbol='plus', eyebrow='') {
  return `<div class="page-heading"><div>${eyebrow ? `<div class="eyebrow">${eyebrow}</div>` : ''}<h1>${title}</h1><p>${description}</p></div>${action ? button(label,action,{symbol}) : ''}</div>`;
}

function content() {
  if (state.view === 'deliveries') return deliveriesPage();
  if (state.view === 'staff') return staffPage();
  if (state.actor.role === 'Delivery staff' && !state.demo_delivery) return deliveriesPage();
  if (state.actor.role === 'Delivery staff') {
    return heading('You’re signed in.','Your delivery staff account is ready for the group system.') + `<section class="panel">${empty('Delivery operations are not connected yet.','Staff allocation, pickup and completion will be available when the delivery module is connected.','','','box')}</section>`;
  }
  switch (state.view) {
    case 'requests': return requestPage();
    case 'quotes': return quotePage();
    case 'customers': return customerPage();
    case 'profile': return profilePage();
    case 'accounts': return accountPage();
    default: return overview();
  }
}

function overview() {
  const drafts = state.requests.filter(r => r.state === 'Draft').length;
  const pending = state.quotes.filter(q => q.decision === 'Pending');
  const accepted = state.quotes.filter(q => q.decision === 'Accepted').length;
  const name = state.actor.role === 'Customer' ? customerName(state.actor.customer_id) : state.actor.username;
  const stat = (label,value,note,symbol,featured=false) => `<div class="stat ${featured ? 'featured' : ''}"><div class="stat-label">${label}${icon(symbol)}</div><div class="stat-value">${value.toString().padStart(2,'0')}</div><div class="stat-note">${note}</div></div>`;
  const nextTitle = pending.length ? `${pending.length} quote${pending.length === 1 ? '' : 's'} awaiting a decision` : drafts ? `${drafts} draft${drafts === 1 ? '' : 's'} ready for your next step` : 'Good things start with a request.';
  const nextDescription = pending.length ? 'Review the price and timing, then let us know how you’d like to proceed.' : drafts ? 'Check the addresses and parcel details before a quote is prepared.' : 'Add the pickup, destination and parcels. We’ll keep everything in one place.';
  return `${heading('Delivery overview','A clear view of your requests, quotes and what comes next.','new-request','New request','plus',`WELCOME BACK, ${esc(name.split(' ')[0])}`)}<section class="stats" aria-label="Workspace summary">${stat('Total requests',state.requests.length,'All your delivery requests','box',true)}${stat('In draft',drafts,'Details you can still edit','edit')}${stat('Awaiting decision',pending.length,'Quotes ready for review','clock')}${stat('Accepted quotes',accepted,'Agreed delivery terms','check')}</section><section class="next-step"><span class="step-icon">${icon(pending.length ? 'quote' : 'leaf')}</span><div class="grow"><h2>${nextTitle}</h2><p>${nextDescription}</p></div>${button(pending.length ? 'Review quotes' : drafts ? 'View requests' : 'Create a request',pending.length ? 'go-quotes' : drafts ? 'go-requests' : 'new-request',{kind:'secondary',symbol:'arrow'})}</section><div class="dashboard-grid"><section class="panel"><header class="panel-header"><div><h2>Recent requests</h2><p>The latest activity in your workspace</p></div>${button('View all requests','go-requests',{kind:'text',symbol:'arrow'})}</header>${state.requests.length ? requestTable([...state.requests].reverse().slice(0,5)) : empty('Your first request starts here.','Tell us where your parcels are going. You can save a draft and finish the details later.','new-request')}</section><aside class="dashboard-aside"><section class="panel mini-summary"><h2>Quotes at a glance</h2><div class="money-total"><small>AUD</small>${money(pending.reduce((sum,q) => sum + Number(q.quoted_cost),0))}</div><p>Total value awaiting a decision</p><div class="summary-row"><span>Pending</span><strong>${pending.length} quote${pending.length === 1 ? '' : 's'}</strong></div><div class="summary-row"><span>Accepted</span><strong>${accepted} quote${accepted === 1 ? '' : 's'}</strong></div><div class="summary-row"><span>Rejected</span><strong>${state.quotes.filter(q => q.decision === 'Rejected').length} quotes</strong></div></section><section class="workflow"><h2>A simple journey</h2>${[['01','Make a request','Add addresses and parcel details.'],['02','Review your quote','See the proposed price and times.'],['03','Make your decision','Accept when the terms work for you.']].map(([n,t,p]) => `<div class="workflow-step"><span class="workflow-number">${n}</span><div><strong>${t}</strong><p>${p}</p></div></div>`).join('')}</section></aside></div>`;
}

function requestTable(requests) {
  return `<div class="table-wrap"><table><thead><tr><th>Request</th><th>Pickup & destination</th><th>Parcels</th><th>Status</th><th><span class="sr-only">Action</span></th></tr></thead><tbody>${requests.map(r => `<tr><td><div class="table-primary" title="${esc(r.request_id)}">${shortId(r.request_id)}</div><div class="table-secondary">${esc(customerName(r.customer_id))}</div></td><td>${route(r)}</td><td>${r.parcels.length.toString().padStart(2,'0')}</td><td>${badge(r.state)}</td><td><button class="row-link" data-action="view-request" data-id="${esc(r.request_id)}" aria-label="View request ${shortId(r.request_id)}">View ${icon('chevron')}</button></td></tr>`).join('')}</tbody></table></div>`;
}

function toolbar(filters, placeholder) {
  return `<div class="toolbar"><div class="tabs" aria-label="Filter by status">${filters.map(f => `<button class="tab ${state.filter === f ? 'selected' : ''}" data-action="filter" data-filter="${f}" aria-pressed="${state.filter === f}">${f}</button>`).join('')}</div><div class="search">${icon('search')}<label for="search" class="sr-only">${placeholder}</label><input id="search" type="search" value="${esc(state.search)}" placeholder="${placeholder}"></div></div>`;
}

function requestPage() {
  const query = state.search.toLowerCase();
  const requests = [...state.requests].reverse().filter(r => (state.filter === 'All' || r.state === state.filter) && [r.request_id,r.pickup_address,r.destination_address,customerName(r.customer_id)].join(' ').toLowerCase().includes(query));
  return heading('Delivery requests','Create a draft, get the details right, and follow its progress.','new-request','New request') + `<section class="panel">${toolbar(['All','Draft','Quoted','Accepted','Rejected'],'Search requests…')}${requests.length ? requestTable(requests) : empty(state.requests.length ? 'No matching requests.' : 'No requests just yet.',state.requests.length ? 'Try another status or search term.' : 'Create your first delivery request to get started.',state.requests.length ? '' : 'new-request')}<div class="record-count">${requests.length} of ${state.requests.length} requests</div></section>`;
}

function quotePage() {
  const query = state.search.toLowerCase();
  const quotes = [...state.quotes].reverse().filter(q => (state.filter === 'All' || q.decision === state.filter) && [q.quote_id,q.request_id,customerName(state.requests.find(r => r.request_id === q.request_id)?.customer_id)].join(' ').toLowerCase().includes(query));
  return heading('Quotes','Clear pricing. Agreed times. A decision that’s yours.',office() ? 'choose-request' : '',office() ? 'Prepare quote' : '') + `<section class="panel">${toolbar(['All','Pending','Accepted','Rejected'],'Search quotes…')}${quotes.length ? `<div class="table-wrap"><table><thead><tr><th>Quote</th><th>Customer</th><th>Amount</th><th>Estimated pickup</th><th>Status</th><th><span class="sr-only">Action</span></th></tr></thead><tbody>${quotes.map(q => `<tr><td><div class="table-primary">${shortId(q.quote_id)}</div><div class="table-secondary">Request ${shortId(q.request_id)}</div></td><td>${esc(customerName(state.requests.find(r => r.request_id === q.request_id)?.customer_id))}</td><td class="table-primary">${money(q.quoted_cost)}</td><td>${esc(date(q.estimated_pickup))}</td><td>${badge(q.decision)}</td><td><button class="row-link" data-action="view-quote" data-id="${esc(q.quote_id)}">Review ${icon('chevron')}</button></td></tr>`).join('')}</tbody></table></div>` : empty(state.quotes.length ? 'No matching quotes.' : 'Your quotes will appear here.',state.quotes.length ? 'Try another status or search term.' : 'Once office staff prepare a quote for your request, you can review it here.','','','quote')}<div class="record-count">${quotes.length} of ${state.quotes.length} quotes</div></section>`;
}

function customerPage() {
  return heading('Customers','Keep contact details together, including customers who book by phone.','new-customer','Add customer') + `<section class="panel"><header class="panel-header"><h2>Customer directory</h2><span class="muted">${state.customers.length} customers</span></header>${state.customers.length ? `<div class="table-wrap"><table><thead><tr><th>Customer</th><th>Phone</th><th>Email</th><th>Requests</th><th><span class="sr-only">Action</span></th></tr></thead><tbody>${state.customers.map(c => `<tr><td><div class="flex"><span class="avatar">${esc(initials(c.display_name))}</span><div><div class="table-primary">${esc(c.display_name)}</div><div class="table-secondary">${shortId(c.customer_id)}</div></div></div></td><td>${esc(c.phone || '—')}</td><td>${esc(c.email || '—')}</td><td>${state.requests.filter(r => r.customer_id === c.customer_id).length}</td><td><button class="row-link" data-action="edit-customer" data-id="${esc(c.customer_id)}">Edit ${icon('chevron')}</button></td></tr>`).join('')}</tbody></table></div>` : empty('A place for every customer.','Add a phone customer here, or let customers create their own account from the sign-in page.','new-customer','Add customer','users')}</section>`;
}

function profilePage() {
  const customer = state.customers.find(c => c.customer_id === state.actor.customer_id);
  if (!customer) return '';
  return heading('My details','Keep your contact information up to date.') + `<div class="profile-grid"><section class="panel profile-form"><h2>Contact information</h2><p class="muted field-hint">Provide at least one phone number or email address.</p><div class="divider"></div><form data-form="customer-update">${formError()}<input type="hidden" name="customer_id" value="${esc(customer.customer_id)}">${contactFields(customer)}<div class="form-footer"><button class="btn primary" type="submit">Save changes ${icon('check')}</button></div></form></section><aside class="profile-aside"><span class="avatar">${esc(initials(customer.display_name))}</span><h2 class="section-label">Your customer account</h2><p>Updating these details keeps all your existing requests and quotes connected to you.</p><p>Signed in as <strong>${esc(state.actor.username)}</strong></p></aside></div>`;
}

function accountPage() {
  return heading('Team accounts','Manage access while keeping customer and delivery history intact.','new-account','Add staff account') + `<section class="panel"><header class="panel-header"><h2>Workspace access</h2><span class="muted">${state.accounts.length} accounts</span></header><div class="table-wrap"><table><thead><tr><th>Username</th><th>Role</th><th>Status</th><th><span class="sr-only">Action</span></th></tr></thead><tbody>${state.accounts.map(a => `<tr><td><div class="flex"><span class="avatar">${esc(initials(a.username))}</span><span class="table-primary">${esc(a.username)}${a.account_id === state.actor.account_id ? ' <span class="muted">(you)</span>' : ''}</span></div></td><td>${esc(a.role)}</td><td>${badge(a.active ? 'Active' : 'Inactive')}</td><td>${a.active && a.account_id !== state.actor.account_id ? `<button class="row-link" data-action="deactivate" data-id="${esc(a.account_id)}">Deactivate</button>` : ''}</td></tr>`).join('')}</tbody></table></div></section>`;
}

function dialog(title, description, body) {
  const element = $('#modal');
  element.innerHTML = `<header class="dialog-header"><div><h2 id="dialog-title">${title}</h2><p>${description}</p></div><button class="icon-button" data-action="close" aria-label="Close dialog">${icon('close')}</button></header><div class="dialog-body">${body}</div>`;
  if (!element.open) element.showModal();
  element.scrollTop = 0;
  const input = $('input:not([type=hidden]), select',element);
  if (input) input.focus();
}

function footer(label, hint='') {
  return `<div class="form-footer">${hint ? `<span class="field-hint">${hint}</span>` : ''}${button('Cancel','close',{kind:'secondary'})}<button type="submit" class="btn primary">${label}${icon('arrow')}</button></div>`;
}

function parcelRow(parcel={}, index=0) {
  return `<div class="parcel-row" data-id="${esc(parcel.parcel_id || '')}"><span class="parcel-no">${String(index+1).padStart(2,'0')}</span><label class="sr-only" for="parcel-${index}">Parcel ${index+1} description</label><input id="parcel-${index}" class="parcel-description" value="${esc(parcel.description || '')}" placeholder="What’s in this parcel?" maxlength="2000"><button type="button" class="icon-button" data-action="remove-parcel" aria-label="Remove parcel ${index+1}">${icon('trash')}</button></div>`;
}

function requestForm(id='') {
  if (!state.customers.length) { afterCustomer = true; customerForm(); return; }
  const request = state.requests.find(r => r.request_id === id);
  const customer = request?.customer_id || state.customers[0]?.customer_id;
  dialog(request ? 'Edit your draft' : 'A new delivery request', 'Start with the details. You can finish an incomplete draft later.', `<form data-form="request" class="dialog-form">${formError()}<input type="hidden" name="request_id" value="${esc(id)}"><div class="field"><label for="customer_id">Customer</label>${request || state.actor.role === 'Customer' ? `<input value="${esc(customerName(customer))}" readonly aria-label="Customer"><input type="hidden" name="customer_id" value="${esc(customer)}">` : `<select id="customer_id" name="customer_id">${state.customers.map(c => `<option value="${esc(c.customer_id)}">${esc(c.display_name)}</option>`).join('')}</select>`}</div><div class="form-row">${field('Pickup address','pickup',{value:request?.pickup_address || '',placeholder:'Street address and suburb'})}${field('Destination address','destination',{value:request?.destination_address || '',placeholder:'Street address and suburb'})}</div><div class="divider"></div><div class="flex between"><div><h3>Parcel details</h3><p class="field-hint">At least one described parcel is needed before quoting.</p></div></div><div id="parcels">${(request?.parcels.length ? request.parcels : [{}]).map(parcelRow).join('')}</div>${button('Add another parcel','add-parcel',{kind:'text',symbol:'plus'})}${footer(request ? 'Save changes' : 'Save draft','Your draft remains editable until a quote is issued.')}</form>`);
}

function requestDetails(id) {
  const r = state.requests.find(item => item.request_id === id);
  if (!r) return;
  const q = state.quotes.find(item => item.request_id === id);
  dialog(`Request ${shortId(id)}`,`${esc(customerName(r.customer_id))} · ${r.parcels.length} parcel${r.parcels.length === 1 ? '' : 's'}`, `<div class="flex between"><span class="section-label">Delivery request</span>${badge(r.state)}</div><div class="detail-meta"><div><small>Pickup address</small><p>${esc(r.pickup_address || 'Not added yet')}</p></div><div><small>Destination address</small><p>${esc(r.destination_address || 'Not added yet')}</p></div></div><div class="divider"></div><h3>Parcels</h3>${r.parcels.length ? `<ul class="detail-list">${r.parcels.map(p => `<li>${icon('box')}${esc(p.description)}</li>`).join('')}</ul>` : '<p class="muted field-hint">No parcels added. Add at least one before quotation.</p>'}<div class="audit">Request ID: ${esc(id)}</div><div class="form-footer">${button('Close','close',{kind:'secondary'})}${r.state === 'Draft' ? button('Edit draft','edit-request',{id,kind:'secondary',symbol:'edit'}) : ''}${r.state === 'Draft' && office() ? button('Prepare quote','prepare-quote',{id,symbol:'quote'}) : q ? button('Review quote','view-quote',{id:q.quote_id,symbol:'arrow'}) : ''}</div>`);
}

function quoteForm(id) {
  const request = state.requests.find(r => r.request_id === id);
  dialog('Prepare a quote',`Request ${shortId(id)} · ${esc(customerName(request.customer_id))}`, `<form data-form="quote" class="dialog-form">${formError()}<input type="hidden" name="request_id" value="${esc(id)}"><div class="hint-box">${route(request)}<div class="field-hint">${request.parcels.length} parcel${request.parcels.length === 1 ? '' : 's'} · The request will be locked once you issue this quote.</div></div>${field('Quoted price (AUD)','cost',{required:true,placeholder:'0.00',extra:'inputmode="decimal"',hint:'Enter the agreed amount with no more than two decimal places.'})}<div class="form-row">${field('Estimated pickup','pickup_time',{type:'datetime-local',required:true})}${field('Estimated delivery','delivery_time',{type:'datetime-local',required:true})}</div><div class="hint-box">Times are in <strong>Melbourne local time</strong>. Delivery must be later than pickup.</div>${footer('Issue quote')}</form>`);
}

function quoteDetails(id) {
  const q = state.quotes.find(item => item.quote_id === id);
  const r = state.requests.find(item => item.request_id === q.request_id);
  dialog(`Quote ${shortId(id)}`,`For ${esc(customerName(r.customer_id))} · Request ${shortId(r.request_id)}`, `<div class="detail-price"><div><div class="eyebrow">Quoted delivery price · AUD</div><strong>${money(q.quoted_cost)}</strong><p>For ${r.parcels.length} parcel${r.parcels.length === 1 ? '' : 's'}</p></div>${badge(q.decision)}</div><div class="detail-meta"><div><small>Pickup</small><p>${esc(r.pickup_address)}</p></div><div><small>Destination</small><p>${esc(r.destination_address)}</p></div><div><small>Estimated pickup</small><p>${esc(date(q.estimated_pickup))}</p></div><div><small>Estimated delivery</small><p>${esc(date(q.estimated_delivery))}</p></div></div><p class="field-hint">All estimates use Melbourne local time.</p><div class="divider"></div><ul class="detail-list">${r.parcels.map(p => `<li>${icon('box')}${esc(p.description)}</li>`).join('')}</ul>${q.delivery_id ? `<div class="hint-box"><strong>${q.delivery_id.startsWith('DEMO-') ? 'Demo delivery reference' : 'Delivery reference'}</strong><br>${esc(q.delivery_id)}${q.delivery_id.startsWith('DEMO-') ? '<br>Your decision is saved. Actual delivery operations are not connected yet.' : ''}</div>` : ''}<div class="audit">Prepared ${esc(date(q.prepared_at))}${q.decision_at ? `<br>Decision recorded ${esc(date(q.decision_at))}` : ''}</div><div class="form-footer">${button('Close','close',{kind:'secondary'})}${q.decision === 'Pending' ? button('Reject quote','decision',{id,kind:'secondary',extra:'data-accept="false"'}) + button('Accept quote','decision',{id,symbol:'check',extra:'data-accept="true"'}) : ''}</div>`);
}

function decisionForm(id, accept) {
  const q = state.quotes.find(item => item.quote_id === id);
  const r = state.requests.find(item => item.request_id === q.request_id);
  dialog(accept ? 'Accept this quote?' : 'Reject this quote?',`Record the decision for ${esc(customerName(r.customer_id))}.`, `<form data-form="decision">${formError()}<input type="hidden" name="quote_id" value="${esc(id)}"><input type="hidden" name="accept" value="${accept}"><div class="hint-box">${accept ? `You’re accepting the quoted price of <strong>${money(q.quoted_cost)}</strong> and the displayed pickup and delivery times. Accepted terms cannot be edited.` : 'This quote will be marked rejected. It will not create a delivery and cannot be accepted later.'}${accept && state.demo_delivery ? '<br><br>This prototype saves a demo delivery reference. Actual delivery operations are not connected yet.' : ''}</div>${footer(accept ? 'Confirm acceptance' : 'Confirm rejection')}</form>`);
}

function customerForm(id='') {
  const customer = state.customers.find(c => c.customer_id === id);
  dialog(customer ? 'Edit customer details' : 'Add a customer', customer ? 'Existing requests stay connected to this customer.' : 'For customers who book by phone. No online account is required.', `<form data-form="${customer ? 'customer-update' : 'customer'}">${formError()}<input type="hidden" name="customer_id" value="${esc(id)}">${contactFields(customer)}<p class="field-hint">Provide at least one phone number or email address.</p>${footer(customer ? 'Save changes' : 'Add customer')}</form>`);
}

function accountForm() {
  dialog('Add a staff account','Give a team member access to the workspace.', `<form data-form="account">${formError()}${field('Username','username',{required:true,autocomplete:'off',placeholder:'e.g. office.mekno'})}<div class="field"><label for="role">Account role</label><select name="role" id="role"><option>Office staff</option><option>Manager</option><option>Delivery staff</option></select></div><div id="staff-id-field" hidden>${field('Existing delivery staff ID','staff_id',{hint:'Use the staff record ID from the delivery module.'})}</div>${field('Password','password',{type:'password',required:true,autocomplete:'new-password',extra:'minlength="8"',placeholder:'At least 8 characters'})}${field('Confirm password','confirm_password',{type:'password',required:true,autocomplete:'new-password'})}${footer('Create account')}</form>`);
}

function deactivateForm(id) {
  const account = state.accounts.find(a => a.account_id === id);
  dialog('Deactivate this account?',esc(account.username),`<form data-form="deactivate">${formError()}<input type="hidden" name="account_id" value="${esc(id)}"><div class="hint-box">This account will no longer be able to sign in. Its customer, request and quote history will remain available.</div>${footer('Deactivate account')}</form>`);
}

function navigate(view) {
  state.view = view; state.filter = 'All'; state.search = '';
  render();
}

function deliveriesPage() {
  const staffRole = state.actor.role === 'Delivery staff';
  return heading('Deliveries', 'Accepted jobs, staff assignments and delivery progress.') +
    `<section class="panel"><header class="panel-header"><h2>${staffRole ? 'My delivery jobs' : 'Delivery jobs'}</h2><span>${state.deliveries.length} deliveries</span></header>${state.deliveries.length ? `<div class="table-wrap"><table><thead><tr><th>Delivery</th><th>Route</th><th>Pickup / delivery</th><th>Status</th><th>Actions</th></tr></thead><tbody>${state.deliveries.map(d => {
      const a = state.allocations.find(a => a.allocation_id === d.current_allocation_id);
      const canOperate = office() || (staffRole && a?.staff_id === state.actor.staff_id);
      return `<tr><td><strong>${shortId(d.delivery_id)}</strong><div class="table-secondary">${money(d.terms.amount)}</div></td><td>${route(d.terms)}</td><td>${esc(date(d.terms.estimated_pickup))}<br>${esc(date(d.terms.estimated_delivery))}</td><td>${badge(d.state)}<div class="table-secondary">${esc(state.delivery_staff.find(s => s.staff_id === a?.staff_id)?.display_name || '')}</div></td><td>${button('Details','delivery-details',{id:d.delivery_id,kind:'text'})}${office() && ['Allocated','Awaiting allocation'].includes(d.state) ? button(a ? 'Reassign' : 'Assign','delivery-assign',{id:d.delivery_id,kind:'text'}) : ''}${office() && a ? button('Release','delivery-release',{id:d.delivery_id,kind:'text'}) : ''}${canOperate && d.state === 'Allocated' ? button('Pick up','delivery-pickup',{id:d.delivery_id,kind:'text'}) : ''}${canOperate && d.state === 'In transit' ? button(d.payment_id ? 'Complete' : 'Record payment',d.payment_id ? 'delivery-complete' : 'delivery-payment',{id:d.delivery_id,kind:'text'}) : ''}</td></tr>`;
    }).join('')}</tbody></table></div>` : empty('No delivery jobs yet.', staffRole ? 'Your assigned jobs will appear here.' : 'Accept a new quote to create a real delivery.')}</section>`;
}

function staffPage() {
  return heading('Staff & availability','Set Melbourne local working periods before allocating jobs.',state.actor.role === 'Manager' ? 'delivery-new-staff' : '', 'Add delivery staff') +
    `<section class="panel"><header class="panel-header"><h2>Delivery team</h2></header>${state.delivery_staff.length ? `<div class="table-wrap"><table><thead><tr><th>Name / staff ID</th><th>Contact</th><th>Status</th><th>Availability</th><th>Actions</th></tr></thead><tbody>${state.delivery_staff.map(s => `<tr><td><strong>${esc(s.display_name)}</strong><div class="table-secondary">${esc(s.staff_id)}</div></td><td>${esc(s.phone)}</td><td>${badge(s.active ? 'Active' : 'Inactive')}</td><td>${(state.schedules.find(x => x.staff_id === s.staff_id)?.periods || []).map(([a,b]) => `${esc(date(a))} – ${esc(date(b))}`).join('<br>') || 'No availability set'}</td><td>${button('Edit availability','delivery-schedule',{id:s.staff_id,kind:'text'})}${state.actor.role === 'Manager' ? button(s.active ? 'Deactivate' : 'Activate','delivery-active',{id:s.staff_id,kind:'text'}) : ''}</td></tr>`).join('')}</tbody></table></div>` : empty('No delivery staff yet.','A manager can create staff records here, then link them to delivery staff accounts.')}</section>`;
}

function deliveryForm(type, id) {
  let title, description = '', body = '', extra = '';
  const d = state.deliveries.find(d => d.delivery_id === id);
  const s = state.delivery_staff.find(s => s.staff_id === id);
  if (type === 'new-staff') {
    title = 'Add delivery staff'; body = field('Full name','name',{required:true}) + field('Phone','phone',{required:true,type:'tel'});
    type = 'staff';
  } else if (type === 'schedule') {
    title = `Availability for ${esc(s.display_name)}`;
    description = 'One period per line: YYYY-MM-DD HH:MM / YYYY-MM-DD HH:MM. Empty removes availability.';
    const value = (state.schedules.find(x => x.staff_id === id)?.periods || []).map(x => x.join(' / ')).join('\n');
    body = `<div class="field"><label for="period-text">Working periods</label><textarea id="period-text" name="period_text" rows="7">${esc(value)}</textarea></div><div class="hint-box">Jobs outside the new availability will be released for reassignment. In-transit jobs must remain covered.</div>`;
    type = 'availability'; extra = `<input type="hidden" name="staff_id" value="${esc(id)}">`;
  } else if (type === 'assign') {
    title = 'Allocate delivery staff'; description = 'Availability and overlapping jobs are checked when you save.';
    body = `<div class="field"><label for="allocate-staff">Delivery staff</label><select id="allocate-staff" name="staff_id" required>${state.delivery_staff.filter(s => s.active).map(s => `<option value="${esc(s.staff_id)}">${esc(s.display_name)}</option>`).join('')}</select></div>${field('Reason (required for reassignment)','reason')}`;
    type = 'allocate';
  } else if (type === 'release') {
    title = 'Release this assignment'; body = field('Reason','reason',{required:true});
  } else if (type === 'payment') {
    title = 'Record collected payment'; description = `Agreed amount: ${money(d.terms.amount)}. This records collection; no bank transaction is performed.`;
    body = field('Amount collected (AUD)','amount',{required:true,value:d.terms.amount});
  } else if (type === 'active') {
    title = s.active ? 'Deactivate delivery staff?' : 'Activate delivery staff?';
    body = '<div class="hint-box">Deactivation releases jobs before pickup. An in-transit assignment prevents deactivation.</div>';
    extra = `<input type="hidden" name="staff_id" value="${esc(id)}"><input type="hidden" name="active" value="${!s.active}">`;
  } else {
    title = type === 'pickup' ? 'Confirm parcel pickup?' : 'Confirm delivery completion?';
    description = type === 'pickup' ? 'Confirm that the assigned staff member collected the parcels.' : 'Confirm that the parcels reached their destination. The agreed payment must already be recorded.';
  }
  dialog(title, description, `<form data-form="delivery-${type}">${formError()}<input type="hidden" name="delivery_id" value="${esc(d?.delivery_id || '')}">${extra}${body}${footer('Confirm')}</form>`);
}

function deliveryDetails(id) {
  const d = state.deliveries.find(x => x.delivery_id === id);
  const history = state.allocations.filter(x => x.delivery_id === id);
  dialog(`Delivery ${shortId(id)}`,'Accepted terms and retained allocation history.', `${badge(d.state)}<div class="detail-meta"><div><small>Pickup</small><p>${esc(d.terms.pickup_address)}</p></div><div><small>Destination</small><p>${esc(d.terms.destination_address)}</p></div><div><small>Pickup estimate</small><p>${esc(date(d.terms.estimated_pickup))}</p></div><div><small>Delivery estimate</small><p>${esc(date(d.terms.estimated_delivery))}</p></div></div><h3>Parcels</h3><ul>${d.terms.parcels.map(p => `<li>${esc(p[1])}</li>`).join('')}</ul><p>Agreed amount: ${money(d.terms.amount)} · Payment ${d.payment_id ? 'recorded' : 'pending'}</p><h3>Allocation history</h3>${history.map(a => `<p>${esc(state.delivery_staff.find(s => s.staff_id === a.staff_id)?.display_name || a.staff_id)} · ${a.current ? 'Current' : esc(a.end_reason)}<br><small>${esc(date(a.assigned_at))}${a.ended_at ? ` → ${esc(date(a.ended_at))}` : ''}</small></p>`).join('') || '<p>No visible staff allocations.</p>'}<h3>Activity</h3>${state.delivery_events.filter(e => e.delivery_id === id).map(e => `<p>${esc(e.action)} · ${esc(date(e.at))}${e.note ? `<br><small>${esc(e.note)}</small>` : ''}</p>`).join('')}<div class="form-footer">${button('Close','close',{kind:'secondary'})}</div>`);
}

document.addEventListener('click', event => {
  const target = event.target.closest('[data-action]');
  if (!target?.dataset.action.startsWith('delivery-')) return;
  const type = target.dataset.action.slice(9);
  if (type === 'details') deliveryDetails(target.dataset.id);
  else deliveryForm(type, target.dataset.id);
});


document.addEventListener('click', async event => {
  const target = event.target.closest('[data-action]');
  if (!target) return;
  const action = target.dataset.action, id = target.dataset.id;
  try {
    switch (action) {
      case 'navigate': navigate(target.dataset.view); break;
      case 'go-quotes': navigate('quotes'); break;
      case 'go-requests': navigate('requests'); break;
      case 'filter': state.filter = target.dataset.filter; render(); break;
      case 'auth-switch': state.authMode = target.dataset.mode; auth(); break;
      case 'menu': $('.sidebar').classList.toggle('open'); break;
      case 'logout':
        Object.assign(state,await api('/api/logout',{}));
        state.authMode = 'login'; state.view = 'overview'; render(); break;
      case 'close': $('#modal').close(); afterCustomer = false; break;
      case 'new-request': requestForm(); break;
      case 'edit-request': requestForm(id); break;
      case 'view-request': requestDetails(id); break;
      case 'prepare-quote': quoteForm(id); break;
      case 'view-quote': quoteDetails(id); break;
      case 'decision': decisionForm(id,target.dataset.accept === 'true'); break;
      case 'choose-request':
        navigate('requests'); state.filter = 'Draft'; render();
        notify('Open a draft request, then choose Prepare quote.'); break;
      case 'new-customer': afterCustomer = false; customerForm(); break;
      case 'edit-customer': customerForm(id); break;
      case 'new-account': accountForm(); break;
      case 'deactivate': deactivateForm(id); break;
      case 'shutdown':
        dialog('Close the workspace?', 'Your saved records will be here when you return.', `<form data-form="shutdown">${formError()}<div class="hint-box">This closes the local app for all open tabs. Open <strong>Start Your Order</strong> again whenever you want to continue.</div>${footer('Close workspace')}</form>`);
        break;
      case 'add-parcel': {
        const rows = [...$('#parcels').children];
        const index = rows.length ? Math.max(...rows.map(r => Number($('input',r).id.split('-')[1]))) + 1 : 0;
        $('#parcels').insertAdjacentHTML('beforeend',parcelRow({},index));
        $('#parcels').lastElementChild.querySelector('input').focus();
        break;
      }
      case 'remove-parcel': target.closest('.parcel-row').remove(); break;
    }
  } catch (error) { notify(error.message); }
});

document.addEventListener('input', event => {
  if (event.target.id === 'search') {
    const position = event.target.selectionStart;
    state.search = event.target.value;
    render();
    $('#search').focus();
    $('#search').setSelectionRange(position,position);
  }
});
document.addEventListener('change', event => {
  if (event.target.id === 'role') $('#staff-id-field').hidden = event.target.value !== 'Delivery staff';
});

document.addEventListener('submit', async event => {
  const form = event.target.closest('[data-form]');
  if (!form) return;
  event.preventDefault();
  const data = Object.fromEntries(new FormData(form));
  const type = form.dataset.form;
  const submit = $('button[type=submit]',form);
  const errorBox = $('.form-error',form);
  errorBox.textContent = '';
  const endpoints = {setup:'/api/setup',login:'/api/login',register:'/api/register',customer:'/api/customers','customer-update':'/api/customers/update',quote:'/api/quotes',decision:'/api/quotes/decision',account:'/api/accounts',deactivate:'/api/accounts/deactivate',shutdown:'/api/shutdown'};
  let endpoint = endpoints[type];
  if (type.startsWith('delivery-')) {
    endpoint = '/api/delivery/' + type.slice(9);
    if (type === 'delivery-availability') data.periods = data.period_text.trim() ? data.period_text.split('\n').filter(x => x.trim()).map(x => x.split('/').map(v => v.trim().replace('T',' '))) : [];
    if (type === 'delivery-active') data.active = data.active === 'true';
  }
  if (type === 'request') {
    data.parcels = [...form.querySelectorAll('.parcel-row')].map(row => ({parcel_id:row.dataset.id,description:$('input',row).value})).filter(p => p.parcel_id || p.description.trim());
    endpoint = data.request_id ? '/api/requests/save' : '/api/requests';
  }
  if (type === 'decision') data.accept = data.accept === 'true';
  submit.disabled = true;
  submit.setAttribute('aria-busy','true');
  try {
    Object.assign(state,await api(endpoint,data));
    if (['setup','login','register'].includes(type)) {
      Object.assign(state,await api('/api/state'));
      state.view = 'overview'; state.filter = 'All'; state.search = '';
    }
    if ($('#modal').open) $('#modal').close();
    if (type === 'shutdown') {
      $('#app').innerHTML = '<main class="loading-screen"><div><h2>All saved. See you next time.</h2><p class="muted">You can close this tab. Open Start Your Order to return.</p></div></main>';
      return;
    }
    render();
    const messages = {setup:'Your workspace is ready.',login:'Welcome back.',register:'Your customer account is ready.',request:data.request_id ? 'Draft changes saved.' : 'Your draft is saved.',quote:'Quote issued. Ready for the customer’s decision.',decision:data.accept ? 'Quote accepted. Your decision is saved.' : 'Quote rejected. Your decision is saved.',customer:'Customer added.','customer-update':'Contact details updated.',account:'Staff account created.',deactivate:'Account deactivated. History retained.'};
    notify(messages[type] || 'Changes saved.');
    if (type === 'customer' && afterCustomer) { afterCustomer = false; requestForm(); }
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.focus();
  } finally {
    submit.disabled = false;
    submit.removeAttribute('aria-busy');
  }
});

(async () => {
  try {
    Object.assign(state,await api('/api/bootstrap'));
    if (state.actor) Object.assign(state,await api('/api/state'));
    render();
  } catch (error) {
    $('#app').innerHTML = `<main class="loading-screen"><div><h2>We couldn’t open the workspace.</h2><p>${esc(error.message)}</p><p>Reopen the local app and refresh this page.</p></div></main>`;
  }
})();
