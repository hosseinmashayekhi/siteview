# دوخت پانوراما با OpenCV C++ (ماژول stitching در بسته‌ی جاوای اندروید موجود نیست)
cmake_minimum_required(VERSION 3.22.1)
project(panostitch)

# مسیر OpenCV Android SDK — با متغیر محیطی OPENCV_ANDROID_SDK قابل تغییر است
if(DEFINED ENV{OPENCV_ANDROID_SDK})
    set(OpenCV_DIR "$ENV{OPENCV_ANDROID_SDK}/sdk/native/jni")
else()
    set(OpenCV_DIR "C:/Users/h1988/android-dev/opencv/OpenCV-android-sdk/sdk/native/jni")
endif()

find_package(OpenCV REQUIRED COMPONENTS core imgproc imgcodecs features2d calib3d stitching)

add_library(panostitch SHARED pano_stitcher.cpp)

target_link_libraries(
    panostitch
    ${OpenCV_LIBS}
    android
    log
)
