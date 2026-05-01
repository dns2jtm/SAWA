module.exports = {
  apps: [
    {
      name: 'sawa-frontend',
      script: 'npm',
      args: 'run dev',
      env: {
        NODE_ENV: 'development',
      },
    },
    {
      name: 'sawa-backend',
      script: 'python3',
      args: '-m uvicorn web.backend.main:app --host 0.0.0.0 --port 8001',
      env: {
        PYTHONUNBUFFERED: '1',
      },
    },
  ],
};
