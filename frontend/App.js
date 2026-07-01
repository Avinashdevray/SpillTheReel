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
} from 'react-native';

const BACKEND_URL = Platform.OS === 'web'
  ? "http://localhost:8000"
  : "https://unreckoned-tommy-briefly.ngrok-free.dev";

export default function App() {
  const [query, setQuery] = useState('');
  const [chatHistory, setChatHistory] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [reelUrl, setReelUrl] = useState('');
  const [showUrlInput, setShowUrlInput] = useState(false);
  const scrollViewRef = useRef(null);
  const fadeAnim = useRef(new Animated.Value(0)).current;

  // Fade in on mount
  useEffect(() => {
    Animated.timing(fadeAnim, {
      toValue: 1,
      duration: 800,
      useNativeDriver: true,
    }).start();
  }, []);

  // Listen for links shared from Instagram

  const sendToBackend = async (url) => {
    setIngesting(true);
    try {
      const res = await fetch(`${BACKEND_URL}/ingest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      if (res.ok) {
        setChatHistory((prev) => [
          ...prev,
          {
            type: 'system',
            text: `🎬 Reel shared! Processing: ${url.substring(0, 50)}...`,
          },
        ]);
      } else {
        setChatHistory((prev) => [
          ...prev,
          { type: 'system', text: '❌ Failed to send reel. Check your backend.' },
        ]);
      }
    } catch (e) {
      setChatHistory((prev) => [
        ...prev,
        { type: 'system', text: '❌ Could not reach backend. Is ngrok running?' },
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
      const res = await fetch(
        `${BACKEND_URL}/chat?q=${encodeURIComponent(userQuery)}`
      );
      const data = await res.json();
      const answer =
        typeof data.response === 'string'
          ? data.response
          : JSON.stringify(data.response, null, 2);
      setChatHistory((prev) => [...prev, { type: 'ai', text: answer }]);
    } catch (e) {
      setChatHistory((prev) => [
        ...prev,
        { type: 'ai', text: '⚠️ Could not reach backend.' },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" />

      {/* Header */}
      <Animated.View style={[styles.header, { opacity: fadeAnim }]}>
        <Text style={styles.logo}>🎬</Text>
        <Text style={styles.title}>SpillTheReel</Text>
        <Text style={styles.subtitle}>Your Reel Memory</Text>
        <TouchableOpacity
          style={styles.addReelBtn}
          onPress={() => setShowUrlInput(!showUrlInput)}
        >
          <Text style={styles.addReelBtnText}>
            {showUrlInput ? '✕ Close' : '+ Add Reel'}
          </Text>
        </TouchableOpacity>
      </Animated.View>

      {/* Manual URL input (for Expo Go since Share Sheet needs native build) */}
      {showUrlInput && (
        <View style={styles.urlInputArea}>
          <TextInput
            style={styles.urlInput}
            value={reelUrl}
            onChangeText={setReelUrl}
            placeholder="Paste Instagram Reel URL here..."
            placeholderTextColor="#6b7280"
            autoCapitalize="none"
            autoCorrect={false}
          />
          <TouchableOpacity
            style={[styles.urlSubmitBtn, !reelUrl.trim() && styles.sendBtnDisabled]}
            onPress={() => {
              if (reelUrl.trim()) {
                sendToBackend(reelUrl.trim());
                setReelUrl('');
                setShowUrlInput(false);
              }
            }}
            disabled={!reelUrl.trim()}
          >
            <Text style={styles.sendBtnText}>📥</Text>
          </TouchableOpacity>
        </View>
      )}

      {/* Ingesting indicator */}
      {ingesting && (
        <View style={styles.ingestBanner}>
          <ActivityIndicator size="small" color="#a78bfa" />
          <Text style={styles.ingestText}>Processing reel...</Text>
        </View>
      )}

      {/* Chat area */}
      <ScrollView
        ref={scrollViewRef}
        style={styles.chat}
        contentContainerStyle={styles.chatContent}
        onContentSizeChange={() =>
          scrollViewRef.current?.scrollToEnd({ animated: true })
        }
      >
        {chatHistory.length === 0 && (
          <View style={styles.emptyState}>
            <Text style={styles.emptyIcon}>💭</Text>
            <Text style={styles.emptyTitle}>No conversations yet</Text>
            <Text style={styles.emptyDesc}>
              Share a Reel from Instagram, then ask questions about it here.
            </Text>
          </View>
        )}

        {chatHistory.map((msg, i) => (
          <View
            key={i}
            style={[
              styles.msgBox,
              msg.type === 'user'
                ? styles.userMsg
                : msg.type === 'system'
                ? styles.systemMsg
                : styles.aiMsg,
            ]}
          >
            <Text
              style={[
                styles.msgText,
                msg.type === 'user'
                  ? styles.userText
                  : msg.type === 'system'
                  ? styles.systemText
                  : styles.aiText,
              ]}
            >
              {msg.type === 'user' ? '🙋 ' : msg.type === 'ai' ? '🧠 ' : ''}
              {msg.text}
            </Text>
          </View>
        ))}

        {isLoading && (
          <View style={[styles.msgBox, styles.aiMsg]}>
            <ActivityIndicator size="small" color="#a78bfa" />
            <Text style={styles.thinkingText}>Thinking...</Text>
          </View>
        )}
      </ScrollView>

      {/* Input area */}
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={0}
      >
        <View style={styles.inputArea}>
          <TextInput
            style={styles.input}
            value={query}
            onChangeText={setQuery}
            placeholder="Ask your reel memory..."
            placeholderTextColor="#6b7280"
            onSubmitEditing={askMemory}
            returnKeyType="send"
            editable={!isLoading}
          />
          <TouchableOpacity
            style={[styles.sendBtn, (!query.trim() || isLoading) && styles.sendBtnDisabled]}
            onPress={askMemory}
            disabled={!query.trim() || isLoading}
          >
            <Text style={styles.sendBtnText}>→</Text>
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0f0f1a',
  },
  header: {
    paddingTop: 60,
    paddingBottom: 20,
    alignItems: 'center',
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(167, 139, 250, 0.15)',
    backgroundColor: 'rgba(15, 15, 26, 0.95)',
  },
  logo: {
    fontSize: 36,
    marginBottom: 4,
  },
  title: {
    fontSize: 28,
    fontWeight: '800',
    color: '#e0d4ff',
    letterSpacing: 1,
  },
  subtitle: {
    fontSize: 14,
    color: '#7c6fae',
    marginTop: 2,
    letterSpacing: 0.5,
  },
  addReelBtn: {
    marginTop: 12,
    paddingHorizontal: 20,
    paddingVertical: 8,
    backgroundColor: 'rgba(109, 40, 217, 0.3)',
    borderRadius: 20,
    borderWidth: 1,
    borderColor: 'rgba(167, 139, 250, 0.3)',
  },
  addReelBtnText: {
    color: '#a78bfa',
    fontSize: 14,
    fontWeight: '600',
  },
  urlInputArea: {
    flexDirection: 'row',
    padding: 12,
    backgroundColor: '#1a1a2e',
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(167, 139, 250, 0.1)',
    alignItems: 'center',
  },
  urlInput: {
    flex: 1,
    backgroundColor: '#0f0f1a',
    borderWidth: 1,
    borderColor: 'rgba(167, 139, 250, 0.2)',
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    fontSize: 14,
    color: '#e0d4ff',
    marginRight: 10,
  },
  urlSubmitBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#6d28d9',
    alignItems: 'center',
    justifyContent: 'center',
  },
  ingestBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 10,
    backgroundColor: 'rgba(167, 139, 250, 0.1)',
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(167, 139, 250, 0.1)',
  },
  ingestText: {
    color: '#a78bfa',
    marginLeft: 8,
    fontSize: 14,
  },
  chat: {
    flex: 1,
  },
  chatContent: {
    padding: 16,
    paddingBottom: 8,
  },
  emptyState: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingTop: 80,
  },
  emptyIcon: {
    fontSize: 48,
    marginBottom: 16,
  },
  emptyTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#a78bfa',
    marginBottom: 8,
  },
  emptyDesc: {
    fontSize: 14,
    color: '#6b7280',
    textAlign: 'center',
    paddingHorizontal: 40,
    lineHeight: 20,
  },
  msgBox: {
    marginBottom: 12,
    padding: 14,
    borderRadius: 16,
    maxWidth: '88%',
  },
  userMsg: {
    alignSelf: 'flex-end',
    backgroundColor: '#6d28d9',
    borderBottomRightRadius: 4,
  },
  aiMsg: {
    alignSelf: 'flex-start',
    backgroundColor: '#1e1b2e',
    borderBottomLeftRadius: 4,
    borderWidth: 1,
    borderColor: 'rgba(167, 139, 250, 0.15)',
  },
  systemMsg: {
    alignSelf: 'center',
    backgroundColor: 'rgba(167, 139, 250, 0.08)',
    borderRadius: 12,
    maxWidth: '95%',
  },
  msgText: {
    fontSize: 15,
    lineHeight: 22,
  },
  userText: {
    color: '#f3f0ff',
  },
  aiText: {
    color: '#d1d5db',
  },
  systemText: {
    color: '#a78bfa',
    fontSize: 13,
    textAlign: 'center',
  },
  thinkingText: {
    color: '#a78bfa',
    marginLeft: 8,
    fontSize: 14,
  },
  inputArea: {
    flexDirection: 'row',
    padding: 16,
    paddingBottom: Platform.OS === 'ios' ? 34 : 16,
    backgroundColor: '#1a1a2e',
    borderTopWidth: 1,
    borderTopColor: 'rgba(167, 139, 250, 0.1)',
    alignItems: 'center',
  },
  input: {
    flex: 1,
    backgroundColor: '#0f0f1a',
    borderWidth: 1,
    borderColor: 'rgba(167, 139, 250, 0.2)',
    borderRadius: 24,
    paddingHorizontal: 20,
    paddingVertical: 12,
    fontSize: 15,
    color: '#e0d4ff',
    marginRight: 10,
  },
  sendBtn: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#6d28d9',
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendBtnDisabled: {
    opacity: 0.4,
  },
  sendBtnText: {
    color: '#fff',
    fontSize: 22,
    fontWeight: '700',
  },
});
