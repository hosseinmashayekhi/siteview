// ترکیب پانورامای 360 با خط لوله‌ی detail در OpenCV:
// زاویه‌های دوربین از ژیروسکوپ/تطبیق تصویری (کاتلین) می‌آیند؛ اینجا
// نگاشت کروی، جبران نور، یافتن خط درز بهینه و ادغام چندباندی انجام می‌شود.
#include <jni.h>
#include <android/log.h>
#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/stitching/detail/warpers.hpp>
#include <opencv2/stitching/detail/exposure_compensate.hpp>
#include <opencv2/stitching/detail/seam_finders.hpp>
#include <opencv2/stitching/detail/blenders.hpp>
#include <opencv2/stitching/detail/util.hpp>
#include <string>
#include <vector>
#include <cmath>

#define TAG "PanoStitchNative"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)

using namespace cv;
using namespace cv::detail;

// بازسازی بردارهای دوربین مطابق buildBasis کاتلین؛ خروجی: R برای warper
// (ستون‌ها: راست، پایینِ تصویر، جلو — در جهان با Y معکوس چون v در warper رو به پایین است)
static Mat rotForWarper(float yaw, float pitch, float roll) {
    const float cy = std::cos(yaw), sy = std::sin(yaw);
    const float cp = std::cos(pitch), sp = std::sin(pitch);
    float fx = sy * cp, fy = sp, fz = cy * cp;
    float rx = cy, ry = 0.f, rz = -sy;
    float ux = fy * rz - fz * ry;
    float uy = fz * rx - fx * rz;
    float uz = fx * ry - fy * rx;
    const float cr = std::cos(roll), sr = std::sin(roll);
    const float nrx = rx * cr + ux * sr;
    const float nry = ry * cr + uy * sr;
    const float nrz = rz * cr + uz * sr;
    ux = -rx * sr + ux * cr;
    uy = -ry * sr + uy * cr;
    uz = -rz * sr + uz * cr;
    rx = nrx; ry = nry; rz = nrz;

    // ستون‌ها: r، ‎-u (پایین)، f — سپس وارون‌سازی Y جهان
    Mat R = (Mat_<float>(3, 3) <<
             rx, -ux, fx,
             -ry, uy, -fy,
             rz, -uz, fz);
    return R;
}

extern "C" JNIEXPORT jint JNICALL
Java_com_siteview_app_data_NativeStitcher_nativeCompose(
        JNIEnv *env, jobject /*thiz*/,
        jobjectArray jPaths, jfloatArray jYpr, jfloat fRel,
        jstring jOutPath, jint canvasW, jint maxDim) {

    const jsize count = env->GetArrayLength(jPaths);
    jfloat *ypr = env->GetFloatArrayElements(jYpr, nullptr);

    std::vector<Mat> images;
    std::vector<Mat> rotations;
    for (jsize i = 0; i < count; i++) {
        auto jPath = (jstring) env->GetObjectArrayElement(jPaths, i);
        const char *path = env->GetStringUTFChars(jPath, nullptr);
        Mat img = imread(path);
        env->ReleaseStringUTFChars(jPath, path);
        if (img.empty()) continue;
        const int big = std::max(img.cols, img.rows);
        if (big > maxDim) {
            const double k = maxDim / (double) big;
            resize(img, img, Size(), k, k, INTER_AREA);
        }
        images.push_back(img);
        rotations.push_back(rotForWarper(ypr[i * 3], ypr[i * 3 + 1], ypr[i * 3 + 2]));
    }
    env->ReleaseFloatArrayElements(jYpr, ypr, JNI_ABORT);
    const int n = (int) images.size();
    LOGI("compose input: %d images, fRel=%.3f", n, (double) fRel);
    if (n < 2) return -1;

    try {
        const float scale = canvasW / (float) (2.0 * CV_PI);
        SphericalWarper warper(scale);

        std::vector<Point> corners(n);
        std::vector<UMat> warped(n), masks(n);
        std::vector<Size> sizes(n);
        for (int i = 0; i < n; i++) {
            const float f = fRel * images[i].cols;
            Mat K = (Mat_<float>(3, 3) <<
                     f, 0, images[i].cols / 2.f,
                     0, f, images[i].rows / 2.f,
                     0, 0, 1);
            Mat w, m;
            Mat srcMask(images[i].size(), CV_8U, Scalar(255));
            corners[i] = warper.warp(images[i], K, rotations[i], INTER_LINEAR, BORDER_REFLECT, w);
            warper.warp(srcMask, K, rotations[i], INTER_NEAREST, BORDER_CONSTANT, m);
            w.copyTo(warped[i]);
            m.copyTo(masks[i]);
            sizes[i] = w.size();
        }

        // جبران اختلاف نور بین فریم‌ها
        Ptr<ExposureCompensator> comp = ExposureCompensator::createDefault(ExposureCompensator::GAIN);
        comp->feed(corners, warped, masks);
        for (int i = 0; i < n; i++) comp->apply(i, corners[i], warped[i], masks[i]);

        // یافتن بهترین خط درز در ناحیه‌های همپوشان
        std::vector<UMat> warpedF(n);
        for (int i = 0; i < n; i++) warped[i].convertTo(warpedF[i], CV_32F);
        DpSeamFinder seamFinder(DpSeamFinder::COLOR);
        seamFinder.find(warpedF, corners, masks);

        // ادغام چندباندی
        MultiBandBlender blender(false, 4);
        Rect roi = resultRoi(corners, sizes);
        blender.prepare(roi);
        for (int i = 0; i < n; i++) {
            Mat w16;
            warped[i].getMat(ACCESS_READ).convertTo(w16, CV_16S);
            blender.feed(w16, masks[i].getMat(ACCESS_READ), corners[i]);
        }
        Mat result16, resultMask;
        blender.blend(result16, resultMask);
        Mat result;
        result16.convertTo(result, CV_8U);
        LOGI("blend done: roi=(%d,%d %dx%d)", roi.x, roi.y, roi.width, roi.height);

        // جاگذاری در بوم کامل ۲:۱
        const int canvasH = canvasW / 2;
        Mat canvas = Mat::zeros(canvasH, canvasW, CV_8UC3);
        Mat covered = Mat::zeros(canvasH, canvasW, CV_8U);
        const int x0 = roi.x + (int) std::lround(CV_PI * scale);
        const int y0 = roi.y;
        for (int yy = 0; yy < result.rows; yy++) {
            const int cyy = y0 + yy;
            if (cyy < 0 || cyy >= canvasH) continue;
            for (int xx = 0; xx < result.cols; xx++) {
                if (!resultMask.at<uchar>(yy, xx)) continue;
                int cxx = x0 + xx;
                // پیچش افقی دور کره
                cxx %= canvasW;
                if (cxx < 0) cxx += canvasW;
                canvas.at<Vec3b>(cyy, cxx) = result.at<Vec3b>(yy, xx);
                covered.at<uchar>(cyy, cxx) = 255;
            }
        }

        // پر کردن قطب‌ها (سوراخ سقف/کف) با کشیدن نزدیک‌ترین پیکسل هر ستون
        for (int xx = 0; xx < canvasW; xx++) {
            int top = -1, bottom = -1;
            for (int yy = 0; yy < canvasH; yy++)
                if (covered.at<uchar>(yy, xx)) { top = yy; break; }
            for (int yy = canvasH - 1; yy >= 0; yy--)
                if (covered.at<uchar>(yy, xx)) { bottom = yy; break; }
            if (top < 0) continue;
            const Vec3b cTop = canvas.at<Vec3b>(top, xx);
            for (int yy = 0; yy < top; yy++) canvas.at<Vec3b>(yy, xx) = cTop;
            const Vec3b cBot = canvas.at<Vec3b>(bottom, xx);
            for (int yy = bottom + 1; yy < canvasH; yy++) canvas.at<Vec3b>(yy, xx) = cBot;
        }

        const char *outPath = env->GetStringUTFChars(jOutPath, nullptr);
        const bool ok = imwrite(outPath, canvas, {IMWRITE_JPEG_QUALITY, 90});
        env->ReleaseStringUTFChars(jOutPath, outPath);
        return ok ? 0 : -3;
    } catch (const cv::Exception &e) {
        LOGI("compose exception: %s", e.what());
        return -2;
    }
}
