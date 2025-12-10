module.exports = {
  apps: [
    {
      name: "gametracker",
      script: "/home/lilacrose/lilacrose.dev2.0/venv/bin/gunicorn",
      args: "--bind 127.0.0.1:5001 --workers 3 --timeout 180 app:app",
      cwd: "/home/lilacrose/lilacrose.dev2.0/gametracker",
      exec_mode: "fork",
      interpreter: "none",
      env: {
        FLASK_ENV: "production",
        PYTHONUNBUFFERED: "1"
      },
      error_file: "/home/lilacrose/pm2_error.log",
      out_file: "/home/lilacrose/pm2_out.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss"
    }
  ]
};