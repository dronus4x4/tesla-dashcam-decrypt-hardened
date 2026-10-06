import AppKit
import SwiftUI
import WebKit

struct TeslaSignInView: NSViewRepresentable {
    let onToken: (String) -> Void
    func makeCoordinator() -> Coordinator { Coordinator(onToken: onToken) }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        let content = WKUserContentController()
        content.add(context.coordinator, name: "dashcamToken")
        // Observe ONLY the Bearer header Tesla's own page sends to its fixed
        // decryption endpoint. Never inspect forms, passwords or MFA inputs.
        content.addUserScript(WKUserScript(source: Self.captureScript,
                                          injectionTime: .atDocumentStart,
                                          forMainFrameOnly: true))
        config.userContentController = content
        let view = WKWebView(frame: .zero, configuration: config)
        view.navigationDelegate = context.coordinator
        view.uiDelegate = context.coordinator
        view.load(URLRequest(url: URL(string: "https://dashcam.tesla.com")!))
        return view
    }
    func updateNSView(_ nsView: WKWebView, context: Context) {}
    static func dismantleNSView(_ nsView: WKWebView, coordinator: Coordinator) {
        nsView.stopLoading()
        nsView.configuration.userContentController.removeScriptMessageHandler(forName: "dashcamToken")
        nsView.configuration.userContentController.removeAllUserScripts()
        nsView.navigationDelegate = nil
        nsView.uiDelegate = nil
    }

    final class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate, WKUIDelegate {
        let onToken: (String) -> Void
        init(onToken: @escaping (String) -> Void) { self.onToken = onToken }
        func userContentController(_ userContentController: WKUserContentController,
                                   didReceive message: WKScriptMessage) {
            guard message.frameInfo.isMainFrame,
                  message.frameInfo.securityOrigin.protocol == "https",
                  message.frameInfo.securityOrigin.host == "dashcam.tesla.com",
                  let token = message.body as? String,
                  !token.isEmpty, token.utf8.count <= 16000,
                  token.unicodeScalars.allSatisfy({ $0.value >= 33 && $0.value <= 126 }) else { return }
            onToken(token)
        }
        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = navigationAction.request.url,
                  url.scheme == "https", let host = url.host,
                  host == "tesla.com" || host.hasSuffix(".tesla.com") else {
                decisionHandler(.cancel)
                return
            }
            decisionHandler(.allow)
        }
        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for navigationAction: WKNavigationAction,
                     windowFeatures: WKWindowFeatures) -> WKWebView? {
            if navigationAction.targetFrame == nil,
               let url = navigationAction.request.url,
               url.scheme == "https", let host = url.host,
               host == "tesla.com" || host.hasSuffix(".tesla.com") {
                webView.load(navigationAction.request)
            }
            return nil
        }
        func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                     initiatedByFrame frame: WKFrameInfo,
                     completionHandler: @escaping ([URL]?) -> Void) {
            let panel = NSOpenPanel()
            panel.canChooseDirectories = parameters.allowsDirectories
            panel.canChooseFiles = true
            panel.allowsMultipleSelection = parameters.allowsMultipleSelection
            completionHandler(panel.runModal() == .OK ? panel.urls : nil)
        }
    }

    static let captureScript = """
    (() => {
      if (location.origin !== 'https://dashcam.tesla.com') return;
      function capture(url, headers) {
        try {
          const u = new URL(url, location.href);
          if (u.origin !== 'https://dashcam.tesla.com' || u.pathname !== '/api/1/decrypt/batch') return;
          const auth = new Headers(headers).get('Authorization');
          if (auth && auth.startsWith('Bearer ')) {
            window.webkit.messageHandlers.dashcamToken.postMessage(auth.slice(7));
          }
        } catch (_) {}
      }
      const originalFetch = window.fetch;
      window.fetch = function(input, init) {
        capture(input instanceof Request ? input.url : input,
                init && init.headers ? init.headers : (input instanceof Request ? input.headers : {}));
        return originalFetch.apply(this, arguments);
      };
      const open = XMLHttpRequest.prototype.open;
      const setHeader = XMLHttpRequest.prototype.setRequestHeader;
      const send = XMLHttpRequest.prototype.send;
      const requests = new WeakMap();
      XMLHttpRequest.prototype.open = function(method, url) {
        requests.set(this, {url, headers: {}});
        return open.apply(this, arguments);
      };
      XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
        const request = requests.get(this);
        if (request) request.headers[name] = value;
        return setHeader.apply(this, arguments);
      };
      XMLHttpRequest.prototype.send = function() {
        const request = requests.get(this);
        if (request) capture(request.url, request.headers);
        return send.apply(this, arguments);
      };
    })();
    """
}
