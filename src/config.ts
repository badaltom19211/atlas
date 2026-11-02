// The normal app uses the same-origin FastAPI server. Preview is an explicit opt-in.
export const isLive = import.meta.env.VITE_APP_MODE !== 'preview';
