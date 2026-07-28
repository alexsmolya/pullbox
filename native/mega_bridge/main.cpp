#include <megaapi.h>

#include <algorithm>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>

#include <unistd.h>

namespace
{
constexpr std::size_t kMaxFieldBytes = 16 * 1024;
constexpr std::size_t kMaxFolderNodes = 10'000;
constexpr int kRequestTimeoutMilliseconds = 120'000;
constexpr int kTransferPollMilliseconds = 200;

volatile std::sig_atomic_t gCancelRequested = 0;
std::mutex gOutputMutex;

struct BridgeRequest
{
    std::string link;
    std::string accountSession;
    std::filesystem::path destination;
};

void handleTermination(int)
{
    gCancelRequested = 1;
}

void emitLine(const std::string& value)
{
    std::lock_guard<std::mutex> lock(gOutputMutex);
    std::cout << value << '\n' << std::flush;
}

std::string hexEncode(const std::string& value)
{
    std::ostringstream output;
    output << std::hex << std::setfill('0');
    for (const unsigned char character: value)
    {
        output << std::setw(2) << static_cast<unsigned>(character);
    }
    return output.str();
}

void emitError(const std::string& code, bool retryable, bool intervention)
{
    emitLine(
        "ERROR " + code + " " + (retryable ? "1" : "0") + " "
        + (intervention ? "1" : "0"));
}

bool parseSize(const std::string& raw, std::size_t& value)
{
    if (raw.empty() || raw.size() > 10
        || !std::all_of(raw.begin(), raw.end(), [](unsigned char character) {
               return character >= '0' && character <= '9';
           }))
    {
        return false;
    }
    try
    {
        const auto parsed = std::stoull(raw);
        if (parsed > kMaxFieldBytes)
        {
            return false;
        }
        value = static_cast<std::size_t>(parsed);
        return true;
    }
    catch (const std::exception&)
    {
        return false;
    }
}

bool readExact(std::string& value, std::size_t length)
{
    value.resize(length);
    if (length == 0)
    {
        return true;
    }
    std::cin.read(value.data(), static_cast<std::streamsize>(length));
    return static_cast<std::size_t>(std::cin.gcount()) == length;
}

bool readBridgeRequest(BridgeRequest& request)
{
    std::string header;
    std::string lengthsLine;
    if (!std::getline(std::cin, header) || header != "PULLBOX_MEGA_BRIDGE 1"
        || !std::getline(std::cin, lengthsLine))
    {
        return false;
    }

    std::istringstream lengths(lengthsLine);
    std::string operation;
    std::string linkLengthRaw;
    std::string sessionLengthRaw;
    std::string destinationLengthRaw;
    std::string trailing;
    if (!(lengths >> operation >> linkLengthRaw >> sessionLengthRaw >> destinationLengthRaw)
        || operation != "DOWNLOAD" || (lengths >> trailing))
    {
        return false;
    }

    std::size_t linkLength = 0;
    std::size_t sessionLength = 0;
    std::size_t destinationLength = 0;
    if (!parseSize(linkLengthRaw, linkLength) || linkLength == 0
        || !parseSize(sessionLengthRaw, sessionLength)
        || !parseSize(destinationLengthRaw, destinationLength) || destinationLength == 0)
    {
        return false;
    }

    std::string destination;
    if (!readExact(request.link, linkLength)
        || !readExact(request.accountSession, sessionLength)
        || !readExact(destination, destinationLength)
        || request.link.find('\0') != std::string::npos
        || request.accountSession.find('\0') != std::string::npos
        || destination.find('\0') != std::string::npos)
    {
        return false;
    }
    request.destination = std::filesystem::path(destination);
    return true;
}

std::string errorCodeFor(int error, bool accountSession)
{
    using mega::MegaError;
    switch (error)
    {
        case MegaError::API_EOVERQUOTA:
            return "mega_quota_exceeded";
        case MegaError::API_ESID:
            return "mega_session_expired";
        case MegaError::API_EACCESS:
            return accountSession ? "mega_auth_required" : "mega_link_unavailable";
        case MegaError::API_ENOENT:
            return "mega_link_unavailable";
        case MegaError::API_EKEY:
        case MegaError::API_EARGS:
            return "mega_link_invalid";
        case MegaError::API_ETOOMANY:
        case MegaError::API_ETOOMANYCONNECTIONS:
            return "mega_rate_limited";
        default:
            return "mega_host_unavailable";
    }
}

bool isRetryable(int error)
{
    using mega::MegaError;
    return error == MegaError::API_EOVERQUOTA || error == MegaError::API_ETOOMANY
           || error == MegaError::API_ETOOMANYCONNECTIONS
           || error == MegaError::API_EINTERNAL || error == MegaError::API_EAGAIN;
}

bool isIntervention(int error)
{
    using mega::MegaError;
    return error == MegaError::API_ESID || error == MegaError::API_EACCESS
           || error == MegaError::API_ENOENT || error == MegaError::API_EKEY
           || error == MegaError::API_EARGS;
}

bool waitForRequest(mega::SynchronousRequestListener& listener, bool accountSession)
{
    if (listener.trywait(kRequestTimeoutMilliseconds) != 0)
    {
        emitError("mega_request_timeout", true, false);
        return false;
    }
    const auto* error = listener.getError();
    const int code = error ? error->getErrorCode() : mega::MegaError::API_EINTERNAL;
    if (code == mega::MegaError::API_OK)
    {
        return true;
    }
    emitError(errorCodeFor(code, accountSession), isRetryable(code), isIntervention(code));
    return false;
}

bool validateAccountSession(mega::MegaApi& api, const std::string& accountSession)
{
    if (accountSession.empty())
    {
        return true;
    }
    mega::SynchronousRequestListener listener;
    api.fastLogin(accountSession.c_str(), &listener);
    return waitForRequest(listener, true);
}

std::string selectedFolderFileHandle(const std::string& link)
{
    constexpr const char* marker = "/file/";
    const auto markerPosition = link.find(marker);
    if (markerPosition == std::string::npos)
    {
        return {};
    }
    const auto start = markerPosition + std::char_traits<char>::length(marker);
    const auto end = link.find_first_of("/?#", start);
    return link.substr(start, end == std::string::npos ? std::string::npos : end - start);
}

bool collectFolderFiles(
    mega::MegaApi& api,
    mega::MegaNode* parent,
    std::vector<std::unique_ptr<mega::MegaNode>>& files,
    std::size_t& visited)
{
    std::unique_ptr<mega::MegaNodeList> children(api.getChildren(parent));
    if (!children)
    {
        return false;
    }
    for (int index = 0; index < children->size(); ++index)
    {
        if (++visited > kMaxFolderNodes)
        {
            return false;
        }
        auto* child = children->get(index);
        if (!child)
        {
            continue;
        }
        if (child->getType() == mega::MegaNode::TYPE_FILE)
        {
            files.emplace_back(child->copy());
        }
        else if (child->getType() == mega::MegaNode::TYPE_FOLDER
                 && !collectFolderFiles(api, child, files, visited))
        {
            return false;
        }
    }
    return true;
}

std::unique_ptr<mega::MegaNode> resolveFolderNode(mega::MegaApi& api, const std::string& link)
{
    mega::SynchronousRequestListener loginListener;
    api.loginToFolder(link.c_str(), &loginListener);
    if (!waitForRequest(loginListener, false))
    {
        return nullptr;
    }

    mega::SynchronousRequestListener fetchListener;
    api.fetchNodes(&fetchListener);
    if (!waitForRequest(fetchListener, false))
    {
        return nullptr;
    }

    const auto selectedHandle = selectedFolderFileHandle(link);
    if (!selectedHandle.empty())
    {
        const auto handle = mega::MegaApi::base64ToHandle(selectedHandle.c_str());
        std::unique_ptr<mega::MegaNode> selected(api.getNodeByHandle(handle));
        if (selected && selected->getType() == mega::MegaNode::TYPE_FILE)
        {
            return selected;
        }
        emitError("mega_link_invalid", false, true);
        return nullptr;
    }

    std::unique_ptr<mega::MegaNode> root(api.getRootNode());
    if (!root)
    {
        emitError("mega_link_unavailable", false, true);
        return nullptr;
    }
    std::vector<std::unique_ptr<mega::MegaNode>> files;
    std::size_t visited = 0;
    if (!collectFolderFiles(api, root.get(), files, visited) || files.size() != 1)
    {
        emitError("mega_folder_ambiguous", false, true);
        return nullptr;
    }
    return std::move(files.front());
}

std::unique_ptr<mega::MegaNode> resolveFileNode(mega::MegaApi& api, const std::string& link)
{
    mega::SynchronousRequestListener listener;
    api.getPublicNode(link.c_str(), &listener);
    if (!waitForRequest(listener, false))
    {
        return nullptr;
    }
    auto* request = listener.getRequest();
    auto* publicNode = request ? request->getPublicMegaNode() : nullptr;
    if (!publicNode || publicNode->getType() != mega::MegaNode::TYPE_FILE)
    {
        emitError("mega_link_invalid", false, true);
        return nullptr;
    }
    return std::unique_ptr<mega::MegaNode>(publicNode->copy());
}

class ProgressTransferListener final: public mega::SynchronousTransferListener
{
public:
    void onTransferUpdate(mega::MegaApi*, mega::MegaTransfer* transfer) override
    {
        if (!transfer)
        {
            return;
        }
        const auto transferred = std::max<std::int64_t>(0, transfer->getTransferredBytes());
        const auto total = std::max<std::int64_t>(0, transfer->getTotalBytes());
        emitLine("PROGRESS " + std::to_string(transferred) + " " + std::to_string(total));
    }
};

bool transferNode(
    mega::MegaApi& api,
    mega::MegaNode& node,
    const std::filesystem::path& destination)
{
    const auto size = std::max<std::int64_t>(0, node.getSize());
    const std::string name = node.getName() ? node.getName() : "download";
    emitLine("META " + std::to_string(size) + " " + hexEncode(name));

    std::unique_ptr<mega::MegaCancelToken> cancelToken(mega::MegaCancelToken::createInstance());
    if (!cancelToken)
    {
        emitError("mega_bridge_internal", true, false);
        return false;
    }
    ProgressTransferListener listener;
    const auto destinationString = destination.string();
    api.startDownload(
        &node,
        destinationString.c_str(),
        nullptr,
        nullptr,
        true,
        cancelToken.get(),
        mega::MegaTransfer::COLLISION_CHECK_ALWAYSERROR,
        mega::MegaTransfer::COLLISION_RESOLUTION_OVERWRITE,
        false,
        &listener);

    while (listener.trywait(kTransferPollMilliseconds) != 0)
    {
        if (gCancelRequested != 0)
        {
            cancelToken->cancel();
        }
    }
    const auto* error = listener.getError();
    const int code = error ? error->getErrorCode() : mega::MegaError::API_EINTERNAL;
    if (gCancelRequested != 0)
    {
        emitError("mega_transfer_cancelled", false, false);
        return false;
    }
    if (code != mega::MegaError::API_OK)
    {
        emitError(errorCodeFor(code, false), isRetryable(code), isIntervention(code));
        return false;
    }
    std::error_code fileError;
    const auto bytes = std::filesystem::file_size(destination, fileError);
    if (fileError)
    {
        emitError("mega_bridge_output_missing", true, false);
        return false;
    }
    emitLine("COMPLETE " + std::to_string(bytes) + " " + hexEncode(name));
    return true;
}

bool isFolderLink(const std::string& link)
{
    return link.find("/folder/") != std::string::npos || link.find("#F!") != std::string::npos;
}

void eraseSecret(std::string& value)
{
    std::fill(value.begin(), value.end(), '\0');
    value.clear();
}
} // namespace

int main()
{
    std::signal(SIGTERM, handleTermination);
    std::signal(SIGINT, handleTermination);

    BridgeRequest request;
    if (!readBridgeRequest(request))
    {
        emitError("mega_bridge_protocol_error", false, true);
        return 2;
    }

    std::error_code pathError;
    const auto parent = request.destination.parent_path();
    if (parent.empty() || !std::filesystem::is_directory(parent, pathError)
        || std::filesystem::exists(request.destination, pathError))
    {
        emitError("mega_bridge_destination_invalid", false, true);
        eraseSecret(request.link);
        eraseSecret(request.accountSession);
        return 2;
    }

    const auto cachePath = parent / (".mega-bridge-cache-" + std::to_string(::getpid()));
    std::filesystem::create_directory(cachePath, pathError);
    if (pathError)
    {
        emitError("mega_bridge_cache_unavailable", true, false);
        eraseSecret(request.link);
        eraseSecret(request.accountSession);
        return 1;
    }

    bool success = false;
    {
        mega::MegaApi api("", cachePath.string().c_str(), "Pullbox/1.1", 1);
        if (validateAccountSession(api, request.accountSession))
        {
            std::unique_ptr<mega::MegaNode> node;
            if (isFolderLink(request.link))
            {
                mega::MegaApi folderApi("", cachePath.string().c_str(), "Pullbox/1.1", 1);
                node = resolveFolderNode(folderApi, request.link);
                if (node)
                {
                    success = transferNode(folderApi, *node, request.destination);
                }
            }
            else
            {
                node = resolveFileNode(api, request.link);
                if (node)
                {
                    success = transferNode(api, *node, request.destination);
                }
            }
        }
    }

    eraseSecret(request.link);
    eraseSecret(request.accountSession);
    std::filesystem::remove_all(cachePath, pathError);
    return success ? 0 : 1;
}
