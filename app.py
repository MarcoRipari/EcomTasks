import os
import flask
from flask import session, redirect, url_for, request
import dash
from dash import html, dcc
import dash_bootstrap_components as dbc
from dash.dependencies import Output, Input, State, ALL
import datetime
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery

# Config
SECRET_KEY = os.environ.get("SECRET_KEY", "dev_only_secret")
CLIENT_SECRETS_FILE = os.environ.get("CLIENT_SECRETS_FILE", "client_secret.json")
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/tasks.readonly'
]

server = flask.Flask(__name__)
server.secret_key = SECRET_KEY

# Dash app
app = dash.Dash(
    __name__,
    server=server,
    url_base_pathname="/",
    external_stylesheets=[dbc.themes.BOOTSTRAP]
)

# Dash layout
app.layout = dbc.Container([
    html.H2("📅 Dashboard Google Calendar & Tasks"),
    html.Div(id="login-status"),
    html.Hr(),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Appuntamenti di oggi"),
                dbc.CardBody(html.Div(id="calendar-events"))
            ])
        ], md=6),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Task di oggi"),
                dbc.CardBody([
                    html.Div(id="tasks-list"),
                    html.Br(),
                    dbc.InputGroup([
                        dbc.Input(id="new-task-title", placeholder="Nuovo task..."),
                        dbc.Button("Aggiungi", id="add-task-btn", color="primary", n_clicks=0)
                    ])
                ])
            ])
        ], md=6)
    ]),

    dcc.Interval(id='interval', interval=5*60*1000, n_intervals=0)
], fluid=True)


# Flask endpoints per OAuth
@server.route("/login")
def login():
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES)
    flow.redirect_uri = url_for('oauth2callback', _external=True)
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true')
    session['state'] = state
    return redirect(authorization_url)

@server.route("/oauth2callback")
def oauth2callback():
    state = session['state']
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        state=state)
    flow.redirect_uri = url_for('oauth2callback', _external=True)
    authorization_response = request.url
    flow.fetch_token(authorization_response=authorization_response)
    credentials = flow.credentials
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'id_token': credentials.id_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    return redirect(url_for('dash_redirect'))

@server.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('dash_redirect'))

@server.route("/")
def dash_redirect():
    return flask.redirect("/")

# Dash callback per UI e dati
@app.callback(
    #dash.dependencies.Output('login-status', 'children'),
    #dash.dependencies.Output('calendar-events', 'children'),
    #dash.dependencies.Output('tasks-list', 'children'),
    #dash.dependencies.Input('interval', 'n_intervals')
    Output('login-status', 'children'),
    Output('calendar-events', 'children'),
    Output('tasks-list', 'children'),
    Input('interval', 'n_intervals')
)
def update_dashboard(n):
    if 'credentials' not in session:
        login_url = "/login"
        return (
            dbc.Alert(html.A("Accedi con Google", href=login_url), color="primary"),
            html.P("Non autenticato."),
            html.P("Non autenticato.")
        )
    creds = google.oauth2.credentials.Credentials(**session['credentials'])
    # Google Calendar
    calendar_service = googleapiclient.discovery.build('calendar', 'v3', credentials=creds)
    now = datetime.datetime.utcnow()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + 'Z'
    end_of_day = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + 'Z'
    events_result = calendar_service.events().list(
        calendarId='primary', timeMin=start_of_day, timeMax=end_of_day,
        singleEvents=True, orderBy='startTime').execute()
    events = events_result.get('items', [])
    # Google Tasks
    tasks_service = googleapiclient.discovery.build('tasks', 'v1', credentials=creds)
    tasks_list = tasks_service.tasks().list(tasklist='@default').execute()
    today = datetime.datetime.utcnow().date()
    todays_tasks = []
    for task in tasks_list.get('items', []):
        due = task.get('due')
        if due:
            due_date = datetime.datetime.fromisoformat(due[:-1]).date()
            if due_date == today:
                todays_tasks.append(task)
    # Render
    event_list = [dbc.ListGroupItem([
        html.B(e.get('summary', 'Senza titolo')),
        html.Br(),
        f"{e['start'].get('dateTime', e['start'].get('date'))} - "
        f"{e['end'].get('dateTime', e['end'].get('date'))}"
    ]) for e in events] if events else [html.P("Nessun appuntamento oggi.")]
    task_list = [dbc.ListGroupItem(t['title']) for t in todays_tasks] if todays_tasks else [html.P("Nessun task per oggi.")]
    return (
        dbc.Alert([
            "Autenticato. ",
            html.A("Logout", href="/logout", style={"marginLeft": "1em"})
        ], color="success"),
        dbc.ListGroup(event_list),
        dbc.ListGroup(task_list)
    )

@app.callback(
    Output('tasks-list', 'children'),
    Input('interval', 'n_intervals'),
    Input({'type': 'complete-task', 'index': ALL}, 'value'),
    State('tasks-list', 'children')
)
def update_tasks(n_intervals, completed_values, current_tasks_ui):
    if 'credentials' not in session:
        return html.P("Non autenticato.")
    
    creds = google.oauth2.credentials.Credentials(**session['credentials'])
    tasks_service = googleapiclient.discovery.build('tasks', 'v1', credentials=creds)

    # Recupera lista
    tasks_list = tasks_service.tasks().list(tasklist='@default').execute()
    today = datetime.datetime.utcnow().date()
    task_elements = []

    for i, task in enumerate(tasks_list.get('items', [])):
        due = task.get('due')
        if due:
            due_date = datetime.datetime.fromisoformat(due[:-1]).date()
            if due_date == today and not task.get('status') == 'completed':
                checkbox_id = {'type': 'complete-task', 'index': task['id']}
                if completed_values and task['id'] in completed_values:
                    tasks_service.tasks().update(
                        tasklist='@default',
                        task=task['id'],
                        body={'status': 'completed'}
                    ).execute()
                    continue
                task_elements.append(
                    dbc.Checkbox(
                        id=checkbox_id,
                        label=task['title'],
                        value=False,
                        style={"marginBottom": "0.5rem"}
                    )
                )

    if not task_elements:
        return html.P("Nessun task per oggi.")

    return task_elements

@app.callback(
    Output('new-task-title', 'value'),
    Input('add-task-btn', 'n_clicks'),
    State('new-task-title', 'value')
)
def add_new_task(n_clicks, task_title):
    if n_clicks and task_title:
        if 'credentials' not in session:
            return ""

        creds = google.oauth2.credentials.Credentials(**session['credentials'])
        tasks_service = googleapiclient.discovery.build('tasks', 'v1', credentials=creds)

        tasks_service.tasks().insert(
            tasklist='@default',
            body={
                'title': task_title,
                'due': datetime.datetime.utcnow().date().isoformat() + 'T00:00:00.000Z'
            }
        ).execute()
        return ""  # reset input
    return task_title


if __name__ == "__main__":
    app.run_server(debug=True)
