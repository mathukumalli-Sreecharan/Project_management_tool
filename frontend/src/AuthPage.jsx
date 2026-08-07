import React, { useState } from 'react';
import { Sparkles, Mail, Lock, User, ArrowRight, AlertCircle } from 'lucide-react';
import { authLogin, authSignup, authGoogle } from './api';
import './AuthPage.css';

export default function AuthPage({ onLogin }) {
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const [errorMsg, setErrorMsg] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErrorMsg('');
    setIsLoading(true);

    try {
      if (isLogin) {
        const res = await authLogin({ email, password });
        onLogin(res.user);
      } else {
        const res = await authSignup({ email, name, password });
        onLogin(res.user);
      }
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleGoogleAuth = async () => {
    setErrorMsg('');
    setIsLoading(true);
    try {
      // In a real OAuth flow, this would intercept a Google Token. 
      const res = await authGoogle({ email: "user@example.com", name: "Project User" });
      onLogin(res.user);
    } catch (err) {
      setErrorMsg("Google Authentication disconnected.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="auth-overlay">
      <div className="auth-ambient-aurora">
        <div className="auth-orb orb-1"></div>
        <div className="auth-orb orb-2"></div>
        <div className="auth-orb orb-3"></div>
      </div>

      <div className="auth-container">
        {/* Brand Side */}
        <div className="auth-brand-panel">
          <div className="auth-logo-group">
            <div className="auth-logo-icon pulse-slow">
              <Sparkles size={32} color="#60a5fa" />
            </div>
            <h1 className="auth-brand-title">VILJE</h1>
            <p className="auth-brand-tagline">PROJECT AUTOMATION</p>
          </div>
          
          <div className="auth-feature-list">
            <div className="auth-feature">
              <div className="feature-dot blue"></div>
              <span>Autonomous Project Generation</span>
            </div>
            <div className="auth-feature">
              <div className="feature-dot green"></div>
              <span>Intelligent Workflow Engine</span>
            </div>
            <div className="auth-feature">
              <div className="feature-dot amber"></div>
              <span>Project Context Vaults</span>
            </div>
          </div>
        </div>

        {/* Form Side */}
        <div className="auth-form-panel glass-panel-premium">
          <h2 className="auth-form-title">
            {isLogin ? 'Welcome Back' : 'Create Account'}
          </h2>
          <p className="auth-form-subtitle">
            {isLogin 
              ? 'Enter your credentials to access the terminal.' 
              : 'Register to deploy agentic workflows.'}
          </p>

          <form onSubmit={handleSubmit} className="auth-form">
            {errorMsg && (
              <div className="auth-error-badge" style={{ padding: '10px 14px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: '8px', color: '#f87171', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                <AlertCircle size={14} />
                <span>{errorMsg}</span>
              </div>
            )}

            {!isLogin && (
              <div className="auth-input-group">
                <label>Full Name</label>
                <div className="auth-input-wrapper">
                  <User size={18} className="input-icon" />
                  <input 
                    type="text" 
                    placeholder="John Doe" 
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required={!isLogin}
                  />
                </div>
              </div>
            )}

            <div className="auth-input-group">
              <label>Email Address</label>
              <div className="auth-input-wrapper">
                <Mail size={18} className="input-icon" />
                <input 
                  type="email" 
                  placeholder="admin@leadcontrol.io" 
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required 
                />
              </div>
            </div>

            <div className="auth-input-group">
              <div className="auth-label-row">
                <label>Password</label>
                {isLogin && <a href="#" className="forgot-password">Forgot?</a>}
              </div>
              <div className="auth-input-wrapper">
                <Lock size={18} className="input-icon" />
                <input 
                  type="password" 
                  placeholder="••••••••••••" 
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required 
                />
              </div>
            </div>

            <button type="submit" className="auth-submit-btn" disabled={isLoading}>
              {isLoading ? (
                <div className="auth-spinner"></div>
              ) : (
                <>
                  {isLogin ? 'AUTHENTICATE' : 'INITIALIZE ACCOUNT'} 
                  <ArrowRight size={16} />
                </>
              )}
            </button>
          </form>

          <div className="auth-divider">
            <span>OR CONTINUE WITH</span>
          </div>

          <button type="button" className="auth-social-btn" onClick={handleGoogleAuth} disabled={isLoading}>
            <svg viewBox="0 0 24 24" width="18" height="18" xmlns="http://www.w3.org/2000/svg">
              <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
              <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
              <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
              <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
            </svg>
            <span>Google</span>
          </button>

          <div className="auth-footer-text">
            {isLogin ? "Don't have clearance? " : "Already have clearance? "}
            <span className="auth-toggle-link" onClick={() => setIsLogin(!isLogin)}>
              {isLogin ? 'Request Access' : 'Authenticate Here'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
