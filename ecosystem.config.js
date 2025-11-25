module.exports = {
  apps: [
    {
      name: "gametracker",
      script: "/home/lilacrose/lilacrose.dev2.0/venv/bin/gunicorn",
      args: "app:app -b 127.0.0.1:5001 -w 4",
      cwd: "/home/lilacrose/lilacrose.dev2.0/gametracker",
      exec_mode: "fork",
      interpreter: "none",
      env: {
        FLASK_ENV: "production"
      }
    }
  ]
};