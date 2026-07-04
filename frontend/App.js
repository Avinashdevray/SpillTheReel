import React, { useEffect, useState, useRef } from 'react';
import {
  StyleSheet,
  Text,
  View,
  TextInput,
  TouchableOpacity,
  ScrollView,
  StatusBar,
  ActivityIndicator,
  Animated,
  KeyboardAvoidingView,
  Platform,
  Alert,
  useWindowDimensions,
  Image,
  Linking
} from 'react-native';
import { auth } from './firebaseConfig';
import {
  onAuthStateChanged,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signOut,
  GoogleAuthProvider,
  signInWithPopup,
} from 'firebase/auth';
import { 
  Film, 
  Send, 
  LogOut, 
  MessageSquare, 
  Plus, 
  X, 
  Eye, 
  EyeOff, 
  AlertCircle,
  PlayCircle,
  ExternalLink
} from 'lucide-react-native';

const BACKEND_URL = "https://prickly-subturriculated-donella.ngrok-free.dev";

// Ultra Premium Linear / Monochrome Tokens
const theme = {
  bg: 'transparent',
  surface: '#0A0A0A',
  surfaceHover: '#111111',
  primary: '#FFFFFF',
  primaryHover: '#F0F0F0',
  primaryText: '#000000',
  secondary: '#111111',
  text: '#FAFAFA',
  textMuted: '#888888',
  border: '#181818',
  error: '#FF453A',
  errorBg: 'rgba(255, 69, 58, 0.1)',
  success: '#32D74B',
  radius: 16,
};

// --- Custom Components ---

const Card = ({ children, style }) => (
  <View style={[styles.card, style]}>
    {children}
  </View>
);

const AnimatedButton = ({ onPress, disabled, style, children }) => {
  const scale = useRef(new Animated.Value(1)).current;

  const handlePressIn = () => {
    Animated.spring(scale, { toValue: 0.97, useNativeDriver: true, speed: 20 }).start();
  };
  const handlePressOut = () => {
    Animated.spring(scale, { toValue: 1, useNativeDriver: true, speed: 20 }).start();
  };

  return (
    <Animated.View style={{ transform: [{ scale }] }}>
      <TouchableOpacity
        activeOpacity={0.8}
        onPressIn={handlePressIn}
        onPressOut={handlePressOut}
        onPress={onPress}
        disabled={disabled}
        style={style}
      >
        {children}
      </TouchableOpacity>
    </Animated.View>
  );
};

const ReelCard = ({ reel }) => (
  <View style={styles.reelCard}>
    {reel.thumbnail ? (
      <Image source={{ uri: reel.thumbnail }} style={styles.reelThumb} resizeMode="cover" />
    ) : (
      <View style={[styles.reelThumb, styles.reelThumbPlaceholder]}>
        <Film size={24} color={theme.textMuted} />
      </View>
    )}
    <View style={styles.reelContent}>
      <Text style={styles.reelAuthor}>@{reel.author || 'unknown'}</Text>
      <Text style={styles.reelSummary} numberOfLines={3}>{reel.summary}</Text>
      <TouchableOpacity 
        style={styles.reelLinkBtn} 
        onPress={() => Linking.openURL(reel.url)}
      >
        <ExternalLink size={14} color={theme.primaryText} />
        <Text style={styles.reelLinkText}>Watch on Instagram</Text>
      </TouchableOpacity>
    </View>
  </View>
);

// --- Main App ---

export default function App() {
  const { width } = useWindowDimensions();
  const isMobile = width < 768;

  // Authentication states
  const [user, setUser] = useState(null);
  const [authEmail, setAuthEmail] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [isSignUp, setIsSignUp] = useState(false);
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  // Main App states
  const [query, setQuery] = useState('');
  const [chatHistory, setChatHistory] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [reelUrl, setReelUrl] = useState('');
  const [showUrlInput, setShowUrlInput] = useState(false);
  const scrollViewRef = useRef(null);
  const fadeAnim = useRef(new Animated.Value(0)).current;

  // Listen for Firebase Auth state changes
  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (currentUser) => {
      setUser(currentUser);
      if (currentUser) {
        setChatHistory([
          {
            type: 'system',
            text: `Welcome to SpillTheReel, ${currentUser.email}.`,
          },
        ]);
        Animated.timing(fadeAnim, {
          toValue: 1,
          duration: 400,
          useNativeDriver: true,
        }).start();
      } else {
        setChatHistory([]);
        fadeAnim.setValue(0);
      }
    });
    return unsubscribe;
  }, []);

  // Handle incoming shares from Web Share Target API (PWA)
  useEffect(() => {
    if (Platform.OS === 'web' && window.location.search) {
      const params = new URLSearchParams(window.location.search);
      const sharedUrl = params.get('url');
      const sharedText = params.get('text');
      
      // Instagram often sends the URL in the "text" field when sharing via Android/iOS intents
      let extractedUrl = '';
      if (sharedUrl && sharedUrl.startsWith('http')) {
        extractedUrl = sharedUrl;
      } else if (sharedText) {
        // Find a URL in the text payload
        const urlMatch = sharedText.match(/https?:\/\/[^\s]+/);
        if (urlMatch) {
          extractedUrl = urlMatch[0];
        }
      }

      if (extractedUrl) {
        setReelUrl(extractedUrl);
        setShowUrlInput(true);
        // Clear the URL parameters so it doesn't trigger again on reload
        window.history.replaceState({}, document.title, window.location.pathname);
      }
    }
  }, []);

  const handleAuth = async () => {
    if (!authEmail.trim() || !authPassword.trim()) {
      setAuthError('Please fill in all fields.');
      return;
    }
    setAuthLoading(true);
    setAuthError('');
    try {
      if (isSignUp) {
        await createUserWithEmailAndPassword(auth, authEmail.trim(), authPassword.trim());
      } else {
        await signInWithEmailAndPassword(auth, authEmail.trim(), authPassword.trim());
      }
    } catch (e) {
      let errorMsg = e.message;
      if (e.code === 'auth/operation-not-allowed') {
        errorMsg = 'Email/Password sign-in is not enabled. Please enable it in Firebase Console → Authentication → Sign-in method.';
      } else if (e.code === 'auth/invalid-email') {
        errorMsg = 'Invalid email address.';
      } else if (e.code === 'auth/wrong-password' || e.code === 'auth/invalid-credential') {
        errorMsg = 'Incorrect email or password.';
      } else if (e.code === 'auth/user-not-found') {
        errorMsg = 'No account found with this email. Try signing up.';
      } else if (e.code === 'auth/email-already-in-use') {
        errorMsg = 'An account with this email already exists. Try signing in.';
      } else if (e.code === 'auth/weak-password') {
        errorMsg = 'Password should be at least 6 characters.';
      } else {
        errorMsg = `Authentication Error: ${e.code || e.message}`;
      }
      setAuthError(errorMsg);
    } finally {
      setAuthLoading(false);
    }
  };

  const handleGoogleSignIn = async () => {
    if (Platform.OS !== 'web') {
      setAuthError('Google Sign-In is only supported on the web version.');
      return;
    }
    
    setAuthLoading(true);
    setAuthError('');
    const provider = new GoogleAuthProvider();
    
    try {
      await signInWithPopup(auth, provider);
    } catch (e) {
      console.error("Google Auth Error:", e);
      let errorMsg = e.message;
      
      if (e.code === 'auth/popup-blocked') {
        errorMsg = 'Popup blocked by browser. Please allow popups for this site.';
      } else if (e.code === 'auth/popup-closed-by-user') {
        errorMsg = 'Google sign-in was cancelled.';
      } else if (e.code === 'auth/unauthorized-domain') {
        errorMsg = 'This domain is not authorized for Google Sign-In. Add it in Firebase Console -> Authentication -> Settings -> Authorized domains.';
      } else if (e.code === 'auth/operation-not-allowed' || e.code === 'auth/configuration-not-found') {
        errorMsg = 'Google sign-in is not enabled. Go to Firebase Console -> Authentication -> Sign-in method -> Enable Google, and ensure you have a support email configured in project settings.';
      }
      
      setAuthError(errorMsg);
    } finally {
      setAuthLoading(false);
    }
  };

  const handleSignOut = async () => {
    try {
      await signOut(auth);
    } catch (e) {
      Alert.alert('Error signing out', e.message);
    }
  };

  const sendToBackend = async (url) => {
    setIngesting(true);
    try {
      const token = await auth.currentUser?.getIdToken();
      const res = await fetch(`${BACKEND_URL}/ingest`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
          'ngrok-skip-browser-warning': 'true',
        },
        body: JSON.stringify({ url }),
      });
      if (res.ok) {
        const data = await res.json();
        setChatHistory((prev) => [
          ...prev,
          {
            type: 'system',
            text: data.message || `Reel processing started: ${url.substring(0, 50)}...`,
          },
        ]);
      } else {
        const errorData = await res.json().catch(() => ({ detail: 'Failed to send reel' }));
        setChatHistory((prev) => [
          ...prev,
          { type: 'error', text: `Ingest failed: ${errorData.detail || 'Check server logs.'}` },
        ]);
      }
    } catch (e) {
      setChatHistory((prev) => [
        ...prev,
        { type: 'error', text: 'Connection refused. Is the backend server running?' },
      ]);
    } finally {
      setIngesting(false);
    }
  };

  const askMemory = async () => {
    if (!query.trim()) return;
    const userQuery = query.trim();
    setQuery('');
    setChatHistory((prev) => [...prev, { type: 'user', text: userQuery }]);
    setIsLoading(true);

    try {
      const token = await auth.currentUser?.getIdToken();
      const res = await fetch(
        `${BACKEND_URL}/chat?q=${encodeURIComponent(userQuery)}`,
        {
          headers: {
            'Authorization': `Bearer ${token}`,
            'ngrok-skip-browser-warning': 'true',
          },
        }
      );
      if (!res.ok) {
        if (res.status === 401) {
          setChatHistory((prev) => [...prev, { type: 'error', text: 'Session expired or unauthorized. Please re-login.' }]);
          return;
        }
        throw new Error('API Error');
      }
      const data = await res.json();
      const responseData = data.response;

      if (typeof responseData === 'object' && responseData !== null && responseData.text) {
        setChatHistory((prev) => [
          ...prev, 
          { type: 'ai', text: responseData.text, reels: responseData.reels || [] }
        ]);
      } else {
        const answer = typeof responseData === 'string'
            ? responseData
            : JSON.stringify(responseData, null, 2);
        setChatHistory((prev) => [...prev, { type: 'ai', text: answer }]);
      }
    } catch (e) {
      setChatHistory((prev) => [
        ...prev,
        { type: 'error', text: 'Could not reach backend.' },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  // --- Render Auth Screen ---
  if (!user) {
    return (
      <View style={styles.container}>
        <StatusBar barStyle="light-content" />
        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          style={styles.authWrapper}
        >
          <Card style={[styles.authCard, isMobile && { 
            padding: 24, 
            paddingVertical: 32,
            borderWidth: 0,
            backgroundColor: 'transparent',
            shadowOpacity: 0
          }]}>
            <View style={styles.authHeader}>
              <Image 
                source={require('./assets/logo.png')} 
                style={styles.fullLogo} 
                resizeMode="contain" 
              />
            </View>

            <View style={styles.authForm}>
              <View style={styles.inputGroup}>
                <TextInput
                  style={styles.authInput}
                  placeholder="Email address"
                  placeholderTextColor={theme.textMuted}
                  value={authEmail}
                  onChangeText={setAuthEmail}
                  autoCapitalize="none"
                  keyboardType="email-address"
                  textContentType="emailAddress"
                />
              </View>
              
              <View style={[styles.inputGroup, styles.passwordGroup]}>
                <TextInput
                  style={[styles.authInput, { flex: 1, marginBottom: 0, borderWidth: 0 }]}
                  placeholder="Password"
                  placeholderTextColor={theme.textMuted}
                  value={authPassword}
                  onChangeText={setAuthPassword}
                  secureTextEntry={!showPassword}
                  textContentType="password"
                />
                <TouchableOpacity 
                  style={styles.eyeIcon} 
                  onPress={() => setShowPassword(!showPassword)}
                >
                  {showPassword ? (
                    <EyeOff size={18} color={theme.textMuted} />
                  ) : (
                    <Eye size={18} color={theme.textMuted} />
                  )}
                </TouchableOpacity>
              </View>

              {authError ? (
                <View style={styles.errorBanner}>
                  <AlertCircle size={16} color={theme.error} />
                  <Text style={styles.errorText}>{authError}</Text>
                </View>
              ) : null}

              <AnimatedButton style={styles.primaryButton} onPress={handleAuth} disabled={authLoading}>
                {authLoading ? (
                  <ActivityIndicator color={theme.primaryText} />
                ) : (
                  <Text style={styles.buttonText}>{isSignUp ? 'Create Account' : 'Sign In'}</Text>
                )}
              </AnimatedButton>

              <View style={styles.divider}>
                <View style={styles.dividerLine} />
                <Text style={styles.dividerText}>or continue with</Text>
                <View style={styles.dividerLine} />
              </View>

              {Platform.OS === 'web' && (
                <AnimatedButton style={styles.googleButton} onPress={handleGoogleSignIn} disabled={authLoading}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.16v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                    <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.16C1.43 8.55 1 10.22 1 12s.43 3.45 1.16 4.93l3.68-2.84z" fill="#FBBC05"/>
                    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.16 7.07l3.68 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
                  </svg>
                  <Text style={styles.googleButtonText}>Google</Text>
                </AnimatedButton>
              )}

              <TouchableOpacity style={styles.toggleLink} onPress={() => setIsSignUp(!isSignUp)}>
                <Text style={styles.toggleLinkText}>
                  {isSignUp ? 'Already have an account? Log in' : "Don't have an account? Sign up"}
                </Text>
              </TouchableOpacity>
            </View>
          </Card>
        </KeyboardAvoidingView>
      </View>
    );
  }

  // --- Render Authenticated Dashboard ---
  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" />

      {/* Header */}
      <Animated.View style={[styles.header, { opacity: fadeAnim }]}>
        <View style={[styles.headerContent, isMobile && { paddingHorizontal: 16 }]}>
          <View style={styles.headerLeft}>
            <View style={styles.iconContainerSmall}>
              <Image 
                source={require('./assets/icon.png')} 
                style={styles.headerIcon} 
                resizeMode="contain" 
              />
            </View>
            <Text style={styles.headerTitle}>SpillTheReel</Text>
          </View>
          <View style={styles.headerRight}>
            <TouchableOpacity 
              style={[styles.addReelBtn, showUrlInput && styles.addReelBtnActive]} 
              onPress={() => setShowUrlInput(!showUrlInput)}
            >
              {showUrlInput ? <X size={16} color={theme.text} /> : <Plus size={16} color={theme.textMuted} />}
              {!isMobile && <Text style={styles.addReelBtnText}>{showUrlInput ? 'Close' : 'Add Content'}</Text>}
            </TouchableOpacity>
            <TouchableOpacity style={styles.iconBtn} onPress={handleSignOut}>
              <LogOut size={18} color={theme.textMuted} />
            </TouchableOpacity>
          </View>
        </View>
      </Animated.View>

      <View style={[styles.mainLayout, !isMobile && styles.mainLayoutDesktop]}>
        {/* Manual URL input overlay */}
        {showUrlInput && (
          <View style={[styles.urlInputArea, isMobile && { paddingHorizontal: 16 }]}>
            <View style={styles.urlInputWrapper}>
              <Film size={18} color={theme.textMuted} style={styles.urlIcon} />
              <TextInput
                style={styles.urlInput}
                value={reelUrl}
                onChangeText={setReelUrl}
                placeholder="Paste Instagram Reel URL..."
                placeholderTextColor={theme.textMuted}
                autoCapitalize="none"
                autoCorrect={false}
              />
              <TouchableOpacity
                style={[styles.urlSubmitBtn, !reelUrl.trim() && styles.btnDisabled]}
                onPress={() => {
                  if (reelUrl.trim()) {
                    sendToBackend(reelUrl.trim());
                    setReelUrl('');
                    setShowUrlInput(false);
                  }
                }}
                disabled={!reelUrl.trim()}
              >
                <Send size={14} color={theme.primaryText} />
              </TouchableOpacity>
            </View>
          </View>
        )}

        {/* Chat input moved to bottom */}        {/* Ingesting indicator */}
        {ingesting && (
          <View style={styles.ingestBanner}>
            <ActivityIndicator size="small" color={theme.textMuted} />
            <Text style={styles.ingestText}>Extracting intelligence...</Text>
          </View>
        )}

        {/* Chat area */}
        <ScrollView
          ref={scrollViewRef}
          style={styles.chat}
          contentContainerStyle={[styles.chatContent, isMobile && { paddingHorizontal: 16, paddingVertical: 16 }, { paddingBottom: 100 }]}
          onContentSizeChange={() =>
            scrollViewRef.current?.scrollToEnd({ animated: true })
          }
        >
          {chatHistory.length === 0 && (
            <View style={styles.emptyState}>
              <View style={styles.emptyIconCircle}>
                <MessageSquare size={28} color={theme.textMuted} strokeWidth={1.5} />
              </View>
              <Text style={styles.emptyTitle}>Empty Workspace</Text>
              <Text style={styles.emptyDesc}>
                Provide a Reel URL to begin indexing. Once indexed, you can query its contents via natural language.
              </Text>
            </View>
          )}

          {chatHistory.map((msg, i) => {
            const isUser = msg.type === 'user';
            const isSystem = msg.type === 'system';
            const isError = msg.type === 'error';
            
            if (isSystem || isError) {
              return (
                <View key={i} style={[styles.systemMsg, isError && styles.errorSystemMsg]}>
                  {isError ? <AlertCircle size={14} color={theme.error} /> : <Film size={14} color={theme.textMuted} />}
                  <Text style={[styles.systemText, isError && styles.errorSystemText]}>{msg.text}</Text>
                </View>
              );
            }

            return (
              <View key={i} style={[styles.msgRow, isUser ? styles.userRow : styles.aiRow]}>
                {!isUser && (
                  <View style={styles.avatarAi}>
                    <PlayCircle size={14} color={theme.textMuted} />
                  </View>
                )}
                <View style={styles.msgContentWrapper}>
                  <View style={[styles.msgBubble, isUser ? styles.userBubble : styles.aiBubble]}>
                    <Text style={[styles.msgText, isUser && styles.userMsgText]}>{msg.text}</Text>
                  </View>
                  {!isUser && msg.reels && msg.reels.length > 0 && (
                    <ScrollView 
                      horizontal 
                      showsHorizontalScrollIndicator={false} 
                      style={styles.reelsScroller}
                      contentContainerStyle={styles.reelsScrollerContent}
                    >
                      {msg.reels.map((reel, rIdx) => (
                        <ReelCard key={rIdx} reel={reel} />
                      ))}
                    </ScrollView>
                  )}
                </View>
              </View>
            );
          })}

          {isLoading && (
            <View style={[styles.msgRow, styles.aiRow]}>
              <View style={styles.avatarAi}>
                <PlayCircle size={14} color={theme.textMuted} />
              </View>
              <View style={[styles.msgBubble, styles.aiBubble, styles.typingBubble]}>
                <ActivityIndicator size="small" color={theme.textMuted} />
                <Text style={styles.thinkingText}>Thinking...</Text>
              </View>
            </View>
          )}
        </ScrollView>

        {/* Floating input pinned to bottom */}
        <View style={[styles.inputFloating, isMobile && { paddingHorizontal: 12 }]}>
          <View style={styles.inputArea}>
            <TextInput
              style={styles.input}
              value={query}
              onChangeText={setQuery}
              placeholder="Ask anything..."
              placeholderTextColor={theme.textMuted}
              onSubmitEditing={askMemory}
              returnKeyType="send"
              editable={!isLoading}
            />
            <TouchableOpacity
              style={[styles.sendBtn, (!query.trim() || isLoading) && styles.btnDisabled]}
              onPress={askMemory}
              disabled={!query.trim() || isLoading}
            >
              <Send size={16} color={theme.primaryText} />
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </View>
  );
}

// --- Styles (Linear/Vercel Aesthetic) ---

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.bg,
  },
  
  // Auth Screen
  authWrapper: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 16,
  },
  card: {
    backgroundColor: theme.surface,
    borderRadius: theme.radius,
    borderWidth: 1,
    borderColor: theme.border,
    padding: 40,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 20 },
    shadowOpacity: 0.5,
    shadowRadius: 40,
  },
  authCard: {
    width: '100%',
    maxWidth: 400,
    alignItems: 'center',
  },
  authHeader: {
    alignItems: 'center',
    marginBottom: 32,
  },
  fullLogo: {
    width: 220,
    height: 120,
  },
  iconContainerSmall: {
    width: 32,
    height: 32,
    borderRadius: theme.radius,
    backgroundColor: theme.surface,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
    borderWidth: 1,
    borderColor: theme.border,
  },
  headerIcon: {
    width: 20,
    height: 20,
  },
  authForm: {
    width: '100%',
  },
  inputGroup: {
    marginBottom: 16,
  },
  passwordGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#050505',
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: theme.radius,
  },
  authInput: {
    backgroundColor: '#050505',
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: theme.radius,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 14,
    color: theme.text,
    outlineStyle: 'none',
  },
  eyeIcon: {
    padding: 14,
  },
  errorBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: theme.bg,
    borderWidth: 1,
    borderColor: theme.errorBg,
    padding: 12,
    borderRadius: theme.radius,
    marginBottom: 16,
  },
  errorText: {
    color: theme.error,
    fontSize: 13,
    marginLeft: 8,
    flex: 1,
    lineHeight: 18,
  },
  primaryButton: {
    backgroundColor: theme.primary,
    borderRadius: theme.radius,
    paddingVertical: 14,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 8,
    shadowColor: theme.primary,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.15,
    shadowRadius: 12,
  },
  buttonText: {
    color: theme.primaryText,
    fontSize: 14,
    fontWeight: '600',
  },
  divider: {
    flexDirection: 'row',
    alignItems: 'center',
    marginVertical: 24,
  },
  dividerLine: {
    flex: 1,
    height: 1,
    backgroundColor: theme.border,
  },
  dividerText: {
    color: theme.textMuted,
    paddingHorizontal: 16,
    fontSize: 12,
    fontWeight: '500',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  googleButton: {
    flexDirection: 'row',
    backgroundColor: '#050505',
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: theme.radius,
    paddingVertical: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  googleButtonText: {
    color: theme.text,
    fontSize: 14,
    fontWeight: '500',
    marginLeft: 10,
  },
  toggleLink: {
    marginTop: 24,
    alignItems: 'center',
    padding: 8,
  },
  toggleLinkText: {
    color: theme.textMuted,
    fontSize: 13,
  },

  // Main App
  header: {
    backgroundColor: theme.bg,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
    paddingTop: Platform.OS === 'ios' ? 50 : 0,
    zIndex: 10,
  },
  headerContent: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 24,
    paddingVertical: 16,
    maxWidth: 1000,
    width: '100%',
    alignSelf: 'center',
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  headerTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: theme.text,
    letterSpacing: -0.2,
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  iconBtn: {
    padding: 10,
    borderRadius: theme.radius,
    backgroundColor: theme.bg,
    borderWidth: 1,
    borderColor: theme.border,
  },
  addReelBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 10,
    backgroundColor: theme.surface,
    borderRadius: theme.radius,
    borderWidth: 1,
    borderColor: theme.border,
    gap: 8,
  },
  addReelBtnActive: {
    backgroundColor: theme.bg,
  },
  addReelBtnText: {
    color: theme.text,
    fontSize: 13,
    fontWeight: '500',
  },
  mainLayout: {
    flex: 1,
    width: '100%',
  },
  mainLayoutDesktop: {
    maxWidth: 800,
    alignSelf: 'center',
    borderLeftWidth: 1,
    borderRightWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.bg,
  },
  urlInputArea: {
    padding: 16,
    paddingHorizontal: 24,
    backgroundColor: 'transparent',
  },
  urlInputWrapper: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#111111',
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 24,
    paddingHorizontal: 16,
  },
  urlIcon: {
    marginRight: 8,
  },
  urlInput: {
    flex: 1,
    paddingVertical: 12,
    fontSize: 14,
    color: theme.text,
    outlineStyle: 'none',
  },
  urlSubmitBtn: {
    width: 32,
    height: 32,
    borderRadius: 6,
    backgroundColor: theme.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  btnDisabled: {
    opacity: 0.5,
  },
  ingestBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    backgroundColor: theme.surface,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
  },
  ingestText: {
    color: theme.textMuted,
    marginLeft: 10,
    fontSize: 13,
  },
  chat: {
    flex: 1,
  },
  chatContent: {
    flexGrow: 1,
    padding: 24,
    paddingBottom: 40,
    gap: 24,
    justifyContent: 'flex-start',
  },
  emptyState: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingTop: 120,
  },
  emptyIconCircle: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: '#111111',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 20,
  },
  emptyTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: theme.text,
    marginBottom: 8,
  },
  emptyDesc: {
    fontSize: 14,
    color: theme.textMuted,
    textAlign: 'center',
    maxWidth: 280,
    lineHeight: 22,
  },
  systemMsg: {
    flexDirection: 'row',
    alignSelf: 'center',
    alignItems: 'center',
    backgroundColor: theme.bg,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 100,
    borderWidth: 1,
    borderColor: theme.border,
    gap: 8,
    marginVertical: 10,
  },
  systemText: {
    color: theme.textMuted,
    fontSize: 12,
  },
  errorSystemMsg: {
    borderColor: theme.errorBg,
  },
  errorSystemText: {
    color: theme.error,
  },
  msgRow: {
    flexDirection: 'row',
    width: '100%',
    alignItems: 'flex-start',
  },
  userRow: {
    justifyContent: 'flex-end',
  },
  aiRow: {
    justifyContent: 'flex-start',
    gap: 16,
  },
  avatarAi: {
    width: 28,
    height: 28,
    borderRadius: theme.radius,
    backgroundColor: theme.surface,
    borderWidth: 1,
    borderColor: theme.border,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 2,
  },
  msgContentWrapper: {
    flex: 1,
    maxWidth: '85%',
  },
  msgBubble: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: theme.radius,
    alignSelf: 'flex-start',
  },
  userBubble: {
    backgroundColor: theme.surface,
    borderWidth: 1,
    borderColor: theme.border,
    alignSelf: 'flex-end',
  },
  aiBubble: {
    backgroundColor: 'transparent',
    paddingHorizontal: 0,
    paddingVertical: 4,
  },
  typingBubble: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 4,
    gap: 10,
  },
  msgText: {
    fontSize: 14,
    lineHeight: 22,
    color: theme.text,
  },
  userMsgText: {
    color: theme.text,
  },
  thinkingText: {
    color: theme.textMuted,
    fontSize: 13,
  },
  
  // Reel Cards
  reelsScroller: {
    marginTop: 12,
  },
  reelsScrollerContent: {
    gap: 12,
    paddingBottom: 4,
  },
  reelCard: {
    width: 260,
    backgroundColor: theme.bg,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: theme.radius,
    overflow: 'hidden',
  },
  reelThumb: {
    width: '100%',
    height: 140,
    backgroundColor: theme.surface,
  },
  reelThumbPlaceholder: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  reelContent: {
    padding: 14,
  },
  reelAuthor: {
    fontSize: 13,
    fontWeight: '600',
    color: theme.text,
    marginBottom: 6,
  },
  reelSummary: {
    fontSize: 12,
    color: theme.textMuted,
    lineHeight: 18,
    marginBottom: 12,
  },
  reelLinkBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: theme.primary,
    paddingVertical: 8,
    borderRadius: 6,
    gap: 6,
  },
  reelLinkText: {
    fontSize: 12,
    fontWeight: '600',
    color: theme.primaryText,
  },

  inputFloating: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    paddingHorizontal: 16,
    paddingBottom: 20,
    paddingTop: 8,
    backgroundColor: 'transparent',
  },
  inputArea: {
    flexDirection: 'row',
    padding: 6,
    paddingLeft: 16,
    alignItems: 'center',
    maxWidth: 720,
    width: '100%',
    alignSelf: 'center',
    backgroundColor: '#1E1E1E',
    borderRadius: 36,
    borderWidth: 0,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 10,
  },
  input: {
    flex: 1,
    backgroundColor: 'transparent',
    borderWidth: 0,
    paddingHorizontal: 8,
    paddingVertical: 12,
    fontSize: 16,
    color: theme.text,
    outlineStyle: 'none',
  },
  sendBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    marginRight: 4,
    backgroundColor: '#FFFFFF',
    alignItems: 'center',
    justifyContent: 'center',
  },
});
